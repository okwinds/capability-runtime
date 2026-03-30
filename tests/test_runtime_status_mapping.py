from __future__ import annotations

"""回归护栏：NodeReport.status → CapabilityStatus 的映射必须稳定且可编排。"""

from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from skills_runtime.core.contracts import AgentEvent

from capability_runtime.config import RuntimeConfig
from capability_runtime.protocol.agent import AgentSpec
from capability_runtime.protocol.capability import CapabilityKind, CapabilitySpec, CapabilityStatus
from capability_runtime.protocol.context import ExecutionContext
from capability_runtime.runtime import Runtime


class _FakeAgent:
    def __init__(self, *, events: List[AgentEvent], **kwargs: Any) -> None:
        self._events = list(events)
        self.kwargs = kwargs

    async def run_stream_async(
        self,
        task: str,
        *,
        run_id: Optional[str] = None,
        initial_history: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[AgentEvent]:
        _ = task
        _ = initial_history
        for ev in self._events:
            # 保证 run_id 一致，避免“上下文 run_id 与事件 run_id”错配导致误诊断
            yield ev.model_copy(update={"run_id": run_id or ev.run_id})


def _mk_runtime(monkeypatch: pytest.MonkeyPatch, *, events: List[AgentEvent]) -> Runtime:
    monkeypatch.setattr("skills_runtime.core.agent.Agent", lambda **kwargs: _FakeAgent(events=events, **kwargs))
    rt = Runtime(RuntimeConfig(mode="sdk_native", workspace_root=Path("."), preflight_mode="off"))
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    return rt


@pytest.mark.asyncio
async def test_run_failed_maps_to_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    rt = _mk_runtime(
        monkeypatch,
        events=[
            AgentEvent(type="run_started", timestamp="2026-02-24T00:00:00Z", run_id="r0", payload={}),
            AgentEvent(
                type="run_failed",
                timestamp="2026-02-24T00:00:01Z",
                run_id="r0",
                payload={"error_kind": "permission", "message": "no"},
            ),
        ],
    )
    out = await rt.run("A", context=ExecutionContext(run_id="r1"))
    assert out.status == CapabilityStatus.FAILED
    assert out.node_report is not None
    assert out.node_report.status == "failed"


@pytest.mark.asyncio
async def test_run_cancelled_maps_to_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    rt = _mk_runtime(
        monkeypatch,
        events=[
            AgentEvent(type="run_started", timestamp="2026-02-24T00:00:00Z", run_id="r0", payload={}),
            AgentEvent(
                type="run_cancelled",
                timestamp="2026-02-24T00:00:01Z",
                run_id="r0",
                payload={"message": "cancelled"},
            ),
        ],
    )
    out = await rt.run("A", context=ExecutionContext(run_id="r1"))
    assert out.status == CapabilityStatus.CANCELLED
    assert out.node_report is not None
    assert out.node_report.status == "incomplete"


@pytest.mark.asyncio
async def test_approval_pending_maps_to_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    rt = _mk_runtime(
        monkeypatch,
        events=[
            AgentEvent(type="run_started", timestamp="2026-02-24T00:00:00Z", run_id="r0", payload={}),
            AgentEvent(
                type="tool_call_requested",
                timestamp="2026-02-24T00:00:00Z",
                run_id="r0",
                step_id="s1",
                payload={"call_id": "c1", "name": "file_write"},
            ),
            AgentEvent(
                type="approval_requested",
                timestamp="2026-02-24T00:00:00Z",
                run_id="r0",
                step_id="s1",
                payload={"tool": "file_write", "approval_key": "k"},
            ),
            AgentEvent(
                type="run_cancelled",
                timestamp="2026-02-24T00:00:01Z",
                run_id="r0",
                payload={"message": "pending approval"},
            ),
        ],
    )
    out = await rt.run("A", context=ExecutionContext(run_id="r1"))
    assert out.status == CapabilityStatus.PENDING
    assert out.node_report is not None
    assert out.node_report.status == "needs_approval"


@pytest.mark.asyncio
async def test_run_waiting_human_maps_to_pending_and_exposes_message(monkeypatch: pytest.MonkeyPatch) -> None:
    rt = _mk_runtime(
        monkeypatch,
        events=[
            AgentEvent(type="run_started", timestamp="2026-03-30T00:00:00Z", run_id="r0", payload={}),
            AgentEvent(
                type="run_waiting_human",
                timestamp="2026-03-30T00:00:01Z",
                run_id="r0",
                payload={
                    "tool": "ask_human",
                    "call_id": "c1",
                    "message": "需要你确认下一步",
                    "error_kind": "human_required",
                    "wal_locator": "wal.jsonl",
                },
            ),
        ],
    )
    out = await rt.run("A", context=ExecutionContext(run_id="r1"))
    assert out.status == CapabilityStatus.PENDING
    assert out.output == "需要你确认下一步"
    assert out.node_report is not None
    assert out.node_report.status == "needs_approval"
    assert out.node_report.completion_reason == "run_waiting_human"
