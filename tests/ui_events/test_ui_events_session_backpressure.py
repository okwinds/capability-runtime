from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

import pytest

from capability_runtime.protocol.capability import CapabilityResult, CapabilityStatus
from capability_runtime.protocol.context import ExecutionContext
from capability_runtime.ui_events.session import RuntimeUIEventsSession
from capability_runtime.ui_events.store import InMemoryRuntimeEventStore
from capability_runtime.ui_events.v1 import RuntimeEvent, StreamLevel


async def _anext(it: AsyncIterator[RuntimeEvent]) -> RuntimeEvent:
    return await it.__anext__()


class _FakeRuntime:
    """
    最小 FakeRuntime：只实现 RuntimeUIEventsSession 所需的三个能力：
    - _register_agent_event_tap / _unregister_agent_event_tap
    - run_stream()：快速产生大量 workflow.* dict + terminal CapabilityResult
    """

    def __init__(self, *, run_id: str, workflow_id: str, steps: int) -> None:
        self._run_id = str(run_id)
        self._workflow_id = str(workflow_id)
        self._steps = int(steps)
        self._taps: List[Callable[..., Any]] = []

    def _register_agent_event_tap(self, tap: Any) -> None:
        self._taps.append(tap)

    def _unregister_agent_event_tap(self, tap: Any) -> None:
        self._taps = [t for t in self._taps if t is not tap]

    async def run_stream(self, capability_id: str, *, input: Dict[str, Any], context: ExecutionContext) -> AsyncIterator[Any]:
        _ = (capability_id, input)
        run_id = str(getattr(context, "run_id", "") or self._run_id)
        wf_id = self._workflow_id
        wf_inst = f"{wf_id}#1"

        yield {"type": "workflow.started", "run_id": run_id, "workflow_id": wf_id, "workflow_instance_id": wf_inst}
        for i in range(self._steps):
            step_id = f"step-{i}"
            yield {
                "type": "workflow.step.started",
                "run_id": run_id,
                "workflow_id": wf_id,
                "workflow_instance_id": wf_inst,
                "step_id": step_id,
            }
            yield {
                "type": "workflow.step.finished",
                "run_id": run_id,
                "workflow_id": wf_id,
                "workflow_instance_id": wf_inst,
                "step_id": step_id,
                "status": "success",
            }
            if i % 200 == 0:
                await asyncio.sleep(0)

        yield {
            "type": "workflow.finished",
            "run_id": run_id,
            "workflow_id": wf_id,
            "workflow_instance_id": wf_inst,
            "status": "success",
        }
        yield CapabilityResult(status=CapabilityStatus.SUCCESS, output={"ok": True})


@pytest.mark.asyncio
async def test_ui_events_session_slow_subscriber_is_cut_off_with_diagnostic_error() -> None:
    """
    回归护栏（task 3.1 / RED）：
    - 慢订阅者不应导致 session 的 per-subscriber 队列无界增长；
    - 当订阅者明显落后时，应被断开或丢弃，并收到可诊断的 error(kind="subscriber_lagged")；
    - 其它正常（fast）订阅者不受影响，仍能拿到终态 run.status != running。

    预期：当前实现（队列无界）下，本用例应失败（RED）。
    """

    ctx = ExecutionContext(run_id="r-backpressure-1", max_depth=10)
    rt = _FakeRuntime(run_id=ctx.run_id, workflow_id="wf.backpressure", steps=3_000)
    sess = RuntimeUIEventsSession(
        runtime=rt,
        capability_id="wf.backpressure",
        input={},
        context=ctx,
        level=StreamLevel.UI,
        store=InMemoryRuntimeEventStore(max_events=200_000),
        heartbeat_interval_s=0.2,
        subscriber_queue_maxsize=16,
    )

    slow_it = sess.subscribe(after_id=None)
    slow_first = await _anext(slow_it)
    assert slow_first.type == "run.status"
    assert slow_first.data.get("status") == "running"
    assert slow_first.rid is not None
    assert isinstance(slow_first.rid, str)

    fast_terminal_status: Optional[str] = None
    fast_seen_lagged = False
    fast_done = asyncio.Event()

    async def _consume_fast() -> None:
        nonlocal fast_terminal_status, fast_seen_lagged
        async for ev in sess.subscribe(after_id=None):
            if ev.type == "error" and ev.data.get("kind") == "subscriber_lagged":
                fast_seen_lagged = True
            if ev.type == "run.status" and ev.data.get("status") != "running":
                fast_terminal_status = str(ev.data.get("status"))
                break
        fast_done.set()

    fast_task = asyncio.create_task(_consume_fast())
    try:
        await asyncio.wait_for(fast_done.wait(), timeout=5.0)
        assert fast_terminal_status is not None, "fast subscriber should observe a terminal run.status"
        assert fast_terminal_status in {"completed", "failed", "cancelled", "pending"}
        assert not fast_seen_lagged, "fast subscriber must not be impacted by slow subscriber backpressure"

        slow_next = await _anext(slow_it)
        assert slow_next.type == "error", (
            "expected slow subscriber to be cut off with subscriber_lagged (bounded queue), "
            f"but got normal event: {slow_next.type}"
        )
        assert slow_next.data.get("kind") == "subscriber_lagged"
        assert slow_next.data.get("message")
        assert slow_next.data.get("policy") == "disconnect"
        queue_maxsize = slow_next.data.get("queue_maxsize")
        assert isinstance(queue_maxsize, int)
        assert queue_maxsize == 16
        assert slow_next.rid is None

        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(_anext(slow_it), timeout=0.5)
    finally:
        try:
            await slow_it.aclose()
        except Exception:
            pass
        if not fast_task.done():
            fast_task.cancel()
            try:
                await fast_task
            except Exception:
                pass
