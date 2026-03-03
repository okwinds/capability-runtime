from __future__ import annotations

import asyncio
import datetime
from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, Optional

import pytest

from skills_runtime.core.contracts import AgentEvent

from capability_runtime.protocol.capability import CapabilityResult, CapabilityStatus
from capability_runtime.protocol.context import ExecutionContext
from capability_runtime.runtime_ui_events_mixin import RuntimeUIEventsMixin
from capability_runtime.ui_events.v1 import RuntimeEvent, StreamLevel


def _rfc3339_now_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


async def _anext(it: AsyncIterator[RuntimeEvent]) -> RuntimeEvent:
    return await it.__anext__()


class _TrackingQueue(asyncio.Queue):
    """
    用于验证：run_ui_events 的 tap 会在入队前过滤其它 run_id 的 AgentEvent，
    避免无关事件入队（即便 projector 会在出队后过滤，也会造成队列堆积风险）。
    """

    last: Optional["_TrackingQueue"] = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        _TrackingQueue.last = self
        self.agent_event_put_nowait_calls = 0

    def put_nowait(self, item: Any) -> None:
        if isinstance(item, tuple) and item and item[0] == "agent_event":
            self.agent_event_put_nowait_calls += 1
        super().put_nowait(item)


class _FakeRuntime(RuntimeUIEventsMixin):
    def __init__(self, *, done: asyncio.Event) -> None:
        self._done = done
        self._config = SimpleNamespace(max_depth=10)
        self._agent_event_taps = []

    async def run_stream(self, capability_id: str, *, input: Dict[str, Any], context: ExecutionContext) -> AsyncIterator[Any]:
        _ = (capability_id, input, context)
        await self._done.wait()
        yield CapabilityResult(status=CapabilityStatus.SUCCESS, output={"ok": True})


@pytest.mark.asyncio
async def test_run_ui_events_drops_other_run_agent_events_before_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    回归护栏：
    - run_ui_events 注册的全局 tap 必须在入队前过滤非本 run 的 AgentEvent；
    - 且在无输入事件时仍能按 heartbeat 正常工作（不会把 heartbeat 误计为入队）。
    """

    import capability_runtime.runtime_ui_events_mixin as mixin_mod

    monkeypatch.setattr(mixin_mod.asyncio, "Queue", _TrackingQueue)

    done = asyncio.Event()
    rt = _FakeRuntime(done=done)
    ctx = ExecutionContext(run_id="r-main", max_depth=10)

    it = rt.run_ui_events(
        "agent.main",
        input={},
        context=ctx,
        level=StreamLevel.UI,
        heartbeat_interval_s=0.05,
    )

    try:
        first = await _anext(it)
        assert first.type == "run.status"
        assert first.data.get("status") == "running"

        q = _TrackingQueue.last
        assert q is not None

        other = AgentEvent(type="run_started", timestamp=_rfc3339_now_utc(), run_id="r-other", payload={})
        rt.emit_agent_event_taps(ev=other, context=ExecutionContext(run_id="r-other", max_depth=10), capability_id="agent.other")

        # 在没有其它输入时，next 应该是 heartbeat（而不是某种因“其它 run 事件入队”导致的输出）
        hb = await asyncio.wait_for(it.__anext__(), timeout=1.0)
        assert hb.type == "heartbeat"

        assert q.agent_event_put_nowait_calls == 0, (
            "expected run_ui_events tap to drop AgentEvent from other run_id before enqueue, "
            f"but agent_event put_nowait was called {q.agent_event_put_nowait_calls} time(s)"
        )
    finally:
        done.set()
        # 清理：消费至终态，避免泄露后台 task（最小 best-effort，避免清理失败覆盖断言原因）
        try:
            for _ in range(50):
                ev = await asyncio.wait_for(it.__anext__(), timeout=2.0)
                if ev.type == "run.status" and ev.data.get("status") in {"completed", "failed", "cancelled", "pending"}:
                    break
        except Exception:
            pass
        try:
            await it.aclose()
        except Exception:
            pass
