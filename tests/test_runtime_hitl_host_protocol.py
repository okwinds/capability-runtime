from __future__ import annotations

from skills_runtime.core.contracts import AgentEvent

from capability_runtime import (
    AgentSpec,
    ApprovalTicket,
    CapabilityKind,
    CapabilitySpec,
    HostRunSnapshot,
    HostRunStatus,
    ResumeIntent,
    Runtime,
    RuntimeConfig,
)
from capability_runtime.host_toolkit.resume import HostResumeState, build_host_resume_state
from capability_runtime.protocol.capability import CapabilityResult, CapabilityStatus
from capability_runtime.types import NodeReport, NodeToolCallReport
from capability_runtime.ui_events.projector import RuntimeUIEventProjector
from capability_runtime.ui_events.v1 import StreamLevel


def _build_runtime() -> Runtime:
    """构造仅用于宿主协议摘要回归的离线 Runtime。"""

    return Runtime(
        RuntimeConfig(
            mode="mock",
            mock_handler=lambda spec, input, context=None: {"ok": True},
        )
    )


def _needs_approval_result() -> CapabilityResult:
    """构造一个 waiting approval 场景的 terminal result。"""

    return CapabilityResult(
        status=CapabilityStatus.PENDING,
        node_report=NodeReport(
            status="needs_approval",
            reason="tool_requires_approval",
            completion_reason="needs_approval",
            run_id="run-approval-1",
            events_path="/tmp/run-approval-1.jsonl",
            tool_calls=[
                NodeToolCallReport(
                    call_id="call-1",
                    name="apply_patch",
                    requires_approval=True,
                    approval_key="approval-1",
                    ok=False,
                )
            ],
            meta={"workflow_id": "wf.review", "workflow_instance_id": "wf-inst-1", "step_id": "review"},
        ),
        metadata={"run_id": "run-approval-1"},
    )


def test_runtime_summarize_host_run_builds_waiting_human_snapshot() -> None:
    """回归：`needs_approval` 终态必须收敛为宿主 `waiting_human` snapshot。"""

    rt = _build_runtime()
    rt.register(
        AgentSpec(base=CapabilitySpec(id="agent.review", kind=CapabilityKind.AGENT, name="Review Agent"))
    )
    result = _needs_approval_result()

    snapshot = rt.summarize_host_run(result, capability_id="agent.review")

    assert isinstance(snapshot, HostRunSnapshot)
    assert snapshot.run_id == "run-approval-1"
    assert snapshot.capability_id == "agent.review"
    assert snapshot.status == HostRunStatus.WAITING_HUMAN
    assert snapshot.node_status == "needs_approval"
    assert snapshot.events_path == "/tmp/run-approval-1.jsonl"
    assert isinstance(snapshot.approval_ticket, ApprovalTicket)
    assert snapshot.approval_ticket.approval_key == "approval-1"
    assert snapshot.approval_ticket.tool_name == "apply_patch"
    assert snapshot.approval_ticket.call_id == "call-1"
    assert snapshot.approval_ticket.workflow_id == "wf.review"
    assert snapshot.approval_ticket.workflow_instance_id == "wf-inst-1"
    assert snapshot.approval_ticket.step_id == "review"


def test_build_resume_intent_and_host_resume_state_expose_waiting_approval_key() -> None:
    """回归：宿主 resume helper 需要恢复 waiting approval key，并构造 ResumeIntent。"""

    rt = _build_runtime()
    intent = rt.build_resume_intent(
        run_id="run-approval-1",
        approval_key="approval-1",
        decision="approved",
        session_id="session-1",
        host_turn_id="turn-1",
    )
    assert isinstance(intent, ResumeIntent)
    assert intent.run_id == "run-approval-1"
    assert intent.approval_key == "approval-1"
    assert intent.decision == "approved"
    assert intent.session_id == "session-1"
    assert intent.host_turn_id == "turn-1"

    events = [
        AgentEvent(
            type="run_started",
            timestamp="2026-03-13T10:00:00Z",
            run_id="run-approval-1",
            payload={},
        ),
        AgentEvent(
            type="approval_requested",
            timestamp="2026-03-13T10:00:01Z",
            run_id="run-approval-1",
            payload={"tool": "apply_patch", "approval_key": "approval-1", "call_id": "call-1"},
        ),
    ]

    state = build_host_resume_state(events=events)
    assert isinstance(state, HostResumeState)
    assert state.run_id == "run-approval-1"
    assert state.waiting_approval_key == "approval-1"
    assert state.approvals["pending_approval_keys_count"] == 1
    assert state.approvals["approved_for_session_keys_count"] == 0


def test_ui_events_terminal_exposes_host_runtime_summary_for_waiting_runs() -> None:
    """回归：terminal UI event 必须携带最小披露的宿主 waiting 状态。"""

    rt = _build_runtime()
    result = _needs_approval_result()

    snapshot = rt.summarize_host_run(result, capability_id="agent.review")
    projector = RuntimeUIEventProjector(run_id="run-approval-1", level=StreamLevel.UI)
    terminal = projector.on_terminal(result)[0]

    assert terminal.type == "run.status"
    assert terminal.data["status"] == "pending"
    assert terminal.data["host_runtime"] == {
        "status": snapshot.status.value,
        "approval_key": "approval-1",
        "tool_name": "apply_patch",
    }
