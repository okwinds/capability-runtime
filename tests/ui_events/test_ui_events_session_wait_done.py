from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Callable, Dict, List

import pytest

from capability_runtime.protocol.capability import CapabilityResult, CapabilityStatus
from capability_runtime.protocol.context import ExecutionContext
from capability_runtime.ui_events.session import RuntimeUIEventsSession
from capability_runtime.ui_events.store import InMemoryRuntimeEventStore
from capability_runtime.ui_events.v1 import RuntimeEvent, StreamLevel


class _FakeRuntime:
    """最小 FakeRuntime：只提供 session 所需的 tap 注册与终态 run_stream。"""

    def __init__(self) -> None:
        self._taps: List[Callable[..., Any]] = []

    def _register_agent_event_tap(self, tap: Any) -> None:
        self._taps.append(tap)

    def _unregister_agent_event_tap(self, tap: Any) -> None:
        self._taps = [t for t in self._taps if t is not tap]

    async def run_stream(self, capability_id: str, *, input: Dict[str, Any], context: ExecutionContext) -> AsyncIterator[Any]:
        _ = (capability_id, input, context)
        await asyncio.sleep(0)
        yield CapabilityResult(status=CapabilityStatus.SUCCESS, output={"ok": True})


class _AppendFailsAfterFirstStore:
    """首条事件允许写入，随后故意失败，用于验证 wait_done() 是否暴露后台异常。"""

    def __init__(self) -> None:
        self._inner = InMemoryRuntimeEventStore(max_events=32)
        self._append_calls = 0

    @property
    def min_rid(self) -> str | None:
        return self._inner.min_rid

    @property
    def max_rid(self) -> str | None:
        return self._inner.max_rid

    def append(self, ev: RuntimeEvent) -> None:
        self._append_calls += 1
        if self._append_calls >= 2:
            raise RuntimeError("store append boom")
        self._inner.append(ev)

    def read_after(self, *, after_id: str | None):
        return self._inner.read_after(after_id=after_id)


async def _anext(it: AsyncIterator[RuntimeEvent]) -> RuntimeEvent:
    return await it.__anext__()


@pytest.mark.asyncio
async def test_wait_done_surfaces_background_session_failure() -> None:
    """
    回归护栏：session 后台任务失败时，wait_done() 不能静默返回。
    """

    rt = _FakeRuntime()
    sess = RuntimeUIEventsSession(
        runtime=rt,
        capability_id="agent.wait-done",
        input={},
        context=ExecutionContext(run_id="r-wait-done", max_depth=10),
        level=StreamLevel.UI,
        store=_AppendFailsAfterFirstStore(),
        heartbeat_interval_s=0.2,
    )

    it = sess.subscribe(after_id=None)
    try:
        first = await _anext(it)
        assert first.type == "run.status"
        assert first.data.get("status") == "running"

        with pytest.raises(RuntimeError, match="store append boom"):
            await asyncio.wait_for(sess.wait_done(), timeout=5.0)
    finally:
        try:
            await it.aclose()
        except Exception:
            pass
