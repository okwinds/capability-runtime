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


async def _next_type(it: AsyncIterator[RuntimeEvent], *, typ: str, timeout_s: float = 2.0) -> RuntimeEvent:
    while True:
        ev = await asyncio.wait_for(it.__anext__(), timeout=timeout_s)
        if ev.type == typ:
            return ev


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
async def test_ui_events_session_uses_workflow_instance_id_to_disambiguate_missing_call_id() -> None:
    """
    回归护栏：
    approvals 事件可能缺 call_id，projector 会 best-effort 通过 step_id 恢复归属。

    该恢复必须以 workflow_instance_id 消歧：当同一 workflow_id 有多个实例且 step_id 相同，
    缺失 call_id 的 approval 不应误关联到“其它实例的 call_id”。
    """

    done = asyncio.Event()
    rt = _FakeRuntime(done=done)
    ctx = ExecutionContext(run_id="r-main", max_depth=10)
    sess = RuntimeUIEventsSession(
        runtime=rt,
        capability_id="agent.ui",
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

        # instance A：先建立 step_id -> call_id 的映射
        tap(
            AgentEvent(
                type="tool_call_requested",
                timestamp=_rfc3339_now_utc(),
                run_id="r-main",
                payload={"call_id": "cA", "name": "apply_patch", "args": {"input": "*** Begin Patch\\n*** End Patch\\n"}},
            ),
            {
                "run_id": "r-main",
                "capability_id": "agent.ui",
                "workflow_id": "wf.ui",
                "workflow_instance_id": "wf.ui#1",
                "step_id": "s1",
            },
        )

        # instance B：覆盖同名 step_id 的映射（若缺少 workflow_instance_id，会污染 instance A）
        tap(
            AgentEvent(
                type="tool_call_requested",
                timestamp=_rfc3339_now_utc(),
                run_id="r-main",
                payload={"call_id": "cB", "name": "apply_patch", "args": {"input": "*** Begin Patch\\n*** End Patch\\n"}},
            ),
            {
                "run_id": "r-main",
                "capability_id": "agent.ui",
                "workflow_id": "wf.ui",
                "workflow_instance_id": "wf.ui#2",
                "step_id": "s1",
            },
        )

        # instance A：approval 缺 call_id，应恢复到 cA（而不是误用 cB）
        tap(
            AgentEvent(
                type="approval_requested",
                timestamp=_rfc3339_now_utc(),
                run_id="r-main",
                payload={"tool": "apply_patch", "approval_key": "appr-A"},
            ),
            {
                "run_id": "r-main",
                "capability_id": "agent.ui",
                "workflow_id": "wf.ui",
                "workflow_instance_id": "wf.ui#1",
                "step_id": "s1",
            },
        )

        appr = await _next_type(it, typ="approval.requested")
        assert appr.data.get("call_id") == "cA", (
            "expected approval.requested (missing call_id) to correlate to call_id from the same workflow instance, "
            f"but got call_id={appr.data.get('call_id')!r}"
        )
    finally:
        done.set()
        try:
            await asyncio.wait_for(sess._done.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pass
        try:
            await it.aclose()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_ui_events_session_uses_wf_frames_to_build_outer_to_inner_path() -> None:
    """
    回归护栏：
    当 tap_ctx 提供 outer→inner 的 wf_frames 时，投影 path 必须包含该嵌套链，
    以便 UI 能按 path 投影 workflow 树并进行多实例消歧。
    """

    done = asyncio.Event()
    rt = _FakeRuntime(done=done)
    ctx = ExecutionContext(run_id="r-main", max_depth=10)
    sess = RuntimeUIEventsSession(
        runtime=rt,
        capability_id="agent.ui",
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

        tap(
            AgentEvent(
                type="tool_call_requested",
                timestamp=_rfc3339_now_utc(),
                run_id="r-main",
                payload={"call_id": "c1", "name": "apply_patch", "args": {"input": "*** Begin Patch\\n*** End Patch\\n"}},
            ),
            {
                "run_id": "r-main",
                "capability_id": "agent.ui",
                "workflow_id": "wf.inner",
                "workflow_instance_id": "wf.inner#1",
                "step_id": "s1",
                "wf_frames": [
                    {"workflow_id": "wf.outer", "workflow_instance_id": "wf.outer#1"},
                    {"workflow_id": "wf.inner", "workflow_instance_id": "wf.inner#1", "step_id": "s1"},
                ],
            },
        )

        tool_req = await _next_type(it, typ="tool.requested")
        wf_ids = [seg.id for seg in tool_req.path if getattr(seg, "kind", None) == "workflow"]
        assert wf_ids[:2] == ["wf.outer#1", "wf.inner#1"], f"expected outer→inner workflow segments, got {wf_ids!r}"
    finally:
        done.set()
        try:
            await asyncio.wait_for(sess._done.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pass
        try:
            await it.aclose()
        except Exception:
            pass
