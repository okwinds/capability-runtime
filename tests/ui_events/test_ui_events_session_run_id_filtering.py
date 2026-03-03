from __future__ import annotations

import asyncio
import datetime
from typing import Any, AsyncIterator, Callable, Dict, List

import pytest

from skills_runtime.core.contracts import AgentEvent

from capability_runtime.protocol.capability import CapabilityResult, CapabilityStatus
from capability_runtime.protocol.context import ExecutionContext
from capability_runtime.ui_events.session import RuntimeUIEventsSession
from capability_runtime.ui_events.store import InMemoryRuntimeEventStore
from capability_runtime.ui_events.v1 import RuntimeEvent, StreamLevel


def _rfc3339_now_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


async def _anext(it: AsyncIterator[RuntimeEvent]) -> RuntimeEvent:
    return await it.__anext__()


class _FakeRuntime:
    """
    最小 FakeRuntime：
    - 保存 session 注册的 agent_event tap，便于测试直接调用
    - run_stream 阻塞直到测试放行，避免 session 很快结束导致 tap 被注销
    """

    def __init__(self, *, done: asyncio.Event) -> None:
        self._done = done
        self.taps: List[Callable[..., Any]] = []

    def _register_agent_event_tap(self, tap: Any) -> None:
        self.taps.append(tap)

    def _unregister_agent_event_tap(self, tap: Any) -> None:
        self.taps = [t for t in self.taps if t is not tap]

    async def run_stream(self, capability_id: str, *, input: Dict[str, Any], context: ExecutionContext) -> AsyncIterator[Any]:
        _ = (capability_id, input, context)
        await self._done.wait()
        yield CapabilityResult(status=CapabilityStatus.SUCCESS, output={"ok": True})


@pytest.mark.asyncio
async def test_ui_events_session_drops_other_run_agent_events_before_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    回归护栏（task 5.1 / RED）：
    - UI events session 只服务于单一 run；
    - 非本 run 的 AgentEvent 应在 tap→输入队列入口处被过滤，避免无关事件入队/堆积/背压。

    预期：当前实现未做入队前过滤，本用例应失败（RED）。
    """

    done = asyncio.Event()
    rt = _FakeRuntime(done=done)
    ctx = ExecutionContext(run_id="r-main", max_depth=10)
    sess = RuntimeUIEventsSession(
        runtime=rt,
        capability_id="agent.main",
        input={},
        context=ctx,
        level=StreamLevel.UI,
        store=InMemoryRuntimeEventStore(max_events=10_000),
        heartbeat_interval_s=0.2,
        input_queue_maxsize=64,
        subscriber_queue_maxsize=16,
    )

    it = sess.subscribe(after_id=None)
    try:
        first = await _anext(it)
        assert first.type == "run.status"
        assert first.data.get("status") == "running"

        assert len(rt.taps) == 1
        tap = rt.taps[0]

        agent_event_put_nowait_calls = 0
        orig_put_nowait = sess._in_q.put_nowait

        def _count_put_nowait(item: Any) -> None:
            nonlocal agent_event_put_nowait_calls
            if isinstance(item, tuple) and item and item[0] == "agent_event":
                agent_event_put_nowait_calls += 1
            orig_put_nowait(item)

        monkeypatch.setattr(sess._in_q, "put_nowait", _count_put_nowait)

        other = AgentEvent(type="run_started", timestamp=_rfc3339_now_utc(), run_id="r-other", payload={})
        tap(other, {"run_id": "r-other", "capability_id": "agent.other"})

        assert agent_event_put_nowait_calls == 0, (
            "expected session tap to drop AgentEvent from other run_id before enqueue, "
            f"but agent_event put_nowait was called {agent_event_put_nowait_calls} time(s)"
        )
    finally:
        done.set()
        try:
            await asyncio.wait_for(sess._done.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            # 清理兜底：本用例聚焦“入队前过滤”的 RED 断言，避免清理失败覆盖断言原因。
            pass
        try:
            await it.aclose()
        except Exception:
            pass
