from __future__ import annotations

"""HITL / wait-resume / approval 的宿主协议收敛层。"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .protocol.capability import CapabilityResult, CapabilityStatus
from .types import NodeReport, NodeToolCallReport


class HostRunStatus(str, Enum):
    """宿主视角的运行状态。"""

    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ApprovalTicket:
    """
    待审批票据。

    参数：
    - run_id：运行 ID
    - capability_id：能力 ID
    - approval_key：审批键
    - tool_name/call_id：审批对应的工具调用标识
    - workflow_id/workflow_instance_id/step_id：可选的 workflow 归属
    - created_at_ms：best-effort 的创建时间戳
    """

    run_id: str
    capability_id: str
    approval_key: str
    tool_name: str | None = None
    call_id: str | None = None
    workflow_id: str | None = None
    workflow_instance_id: str | None = None
    step_id: str | None = None
    created_at_ms: int = 0


@dataclass(frozen=True)
class ResumeIntent:
    """宿主续跑意图。"""

    run_id: str
    approval_key: str | None = None
    decision: str | None = None
    session_id: str | None = None
    host_turn_id: str | None = None


@dataclass(frozen=True)
class HostRunSnapshot:
    """
    宿主运行摘要。

    参数：
    - run_id：运行 ID
    - capability_id：能力 ID
    - status：宿主状态
    - node_status：NodeReport.status 原值（若有）
    - approval_ticket：等待审批时的票据
    - resume_state：宿主恢复所需的最小状态
    - events_path：证据链 events 定位符
    """

    run_id: str
    capability_id: str
    status: HostRunStatus
    node_status: str | None = None
    approval_ticket: ApprovalTicket | None = None
    resume_state: dict[str, Any] = field(default_factory=dict)
    events_path: str | None = None


def build_resume_intent(
    *,
    run_id: str,
    approval_key: str | None = None,
    decision: str | None = None,
    session_id: str | None = None,
    host_turn_id: str | None = None,
) -> ResumeIntent:
    """
    构造宿主续跑意图。

    参数：
    - run_id：运行 ID
    - approval_key：可选审批键
    - decision：可选审批决定
    - session_id：可选会话 ID
    - host_turn_id：可选宿主 turn ID
    """

    return ResumeIntent(
        run_id=run_id,
        approval_key=approval_key,
        decision=decision,
        session_id=session_id,
        host_turn_id=host_turn_id,
    )


def build_approval_ticket_from_report(
    report: NodeReport | None,
    *,
    capability_id: str,
) -> ApprovalTicket | None:
    """
    从 NodeReport 恢复 ApprovalTicket。

    参数：
    - report：NodeReport
    - capability_id：能力 ID

    返回：
    - 待审批票据；无法恢复时返回 None
    """

    if report is None:
        return None

    call = _select_waiting_tool_call(report)
    if call is None:
        return None

    approval_key = (call.approval_key or "").strip()
    if not approval_key:
        return None

    meta = report.meta if isinstance(report.meta, dict) else {}
    created_at_ms = meta.get("approval_requested_at_ms")
    if not isinstance(created_at_ms, int):
        created_at_ms = 0

    return ApprovalTicket(
        run_id=_resolve_run_id(result=None, report=report, metadata=None),
        capability_id=capability_id,
        approval_key=approval_key,
        tool_name=str(call.name or "").strip() or None,
        call_id=str(call.call_id or "").strip() or None,
        workflow_id=_optional_text(meta.get("workflow_id")),
        workflow_instance_id=_optional_text(meta.get("workflow_instance_id")),
        step_id=_optional_text(meta.get("step_id")),
        created_at_ms=created_at_ms,
    )


def summarize_host_run_result(result: CapabilityResult, *, capability_id: str) -> HostRunSnapshot:
    """
    把 terminal result 收敛成宿主运行摘要。

    参数：
    - result：终态 CapabilityResult
    - capability_id：能力 ID
    """

    report = result.node_report
    node_status = getattr(report, "status", None)
    approval_ticket = build_approval_ticket_from_report(report, capability_id=capability_id)
    status = _map_host_run_status(result=result, report=report, approval_ticket=approval_ticket)

    resume_state: dict[str, Any] = {}
    if approval_ticket is not None:
        resume_state["waiting_approval_key"] = approval_ticket.approval_key

    return HostRunSnapshot(
        run_id=_resolve_run_id(result=result, report=report, metadata=result.metadata),
        capability_id=capability_id,
        status=status,
        node_status=node_status,
        approval_ticket=approval_ticket,
        resume_state=resume_state,
        events_path=_optional_text(getattr(report, "events_path", None)),
    )


def project_host_runtime_data(result: CapabilityResult, *, capability_id: str = "") -> dict[str, Any] | None:
    """
    为 UI terminal 事件投影最小宿主状态。

    参数：
    - result：终态 CapabilityResult
    - capability_id：可选能力 ID；投影等待审批最小摘要时可为空
    """

    snapshot = summarize_host_run_result(result, capability_id=capability_id)
    if snapshot.status != HostRunStatus.WAITING_HUMAN or snapshot.approval_ticket is None:
        return None
    return {
        "status": snapshot.status.value,
        "approval_key": snapshot.approval_ticket.approval_key,
        "tool_name": snapshot.approval_ticket.tool_name,
    }


def _select_waiting_tool_call(report: NodeReport) -> NodeToolCallReport | None:
    """选择最能代表 waiting approval 的工具调用。"""

    waiting_candidates: list[NodeToolCallReport] = []
    fallback_candidates: list[NodeToolCallReport] = []
    for call in report.tool_calls:
        if call.requires_approval:
            fallback_candidates.append(call)
            if call.approval_key and call.approval_decision is None:
                waiting_candidates.append(call)
    if waiting_candidates:
        return waiting_candidates[0]
    if report.status == "needs_approval" and fallback_candidates:
        return fallback_candidates[0]
    return None


def _map_host_run_status(
    *,
    result: CapabilityResult,
    report: NodeReport | None,
    approval_ticket: ApprovalTicket | None,
) -> HostRunStatus:
    """将 terminal result + NodeReport 映射为宿主状态。"""

    if getattr(report, "status", None) == "needs_approval" or approval_ticket is not None:
        return HostRunStatus.WAITING_HUMAN
    if result.status == CapabilityStatus.SUCCESS:
        return HostRunStatus.COMPLETED
    if result.status == CapabilityStatus.FAILED:
        return HostRunStatus.FAILED
    if result.status == CapabilityStatus.CANCELLED:
        return HostRunStatus.CANCELLED
    return HostRunStatus.RUNNING


def _resolve_run_id(
    *,
    result: CapabilityResult | None,
    report: NodeReport | None,
    metadata: dict[str, Any] | None,
) -> str:
    """按 report → metadata → result.metadata 的顺序恢复 run_id。"""

    if report is not None and isinstance(report.run_id, str) and report.run_id.strip():
        return report.run_id.strip()
    if isinstance(metadata, dict):
        run_id = metadata.get("run_id")
        if isinstance(run_id, str) and run_id.strip():
            return run_id.strip()
    if result is not None and isinstance(result.metadata, dict):
        run_id = result.metadata.get("run_id")
        if isinstance(run_id, str) and run_id.strip():
            return run_id.strip()
    return ""


def _optional_text(value: Any) -> Optional[str]:
    """把可选字段归一为非空字符串。"""

    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
