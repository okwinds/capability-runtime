from __future__ import annotations

"""Workflow host-facing runtime state / replay surface."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .host_protocol import build_approval_ticket_from_report
from .protocol.capability import CapabilityResult, CapabilityStatus


class WorkflowRunStatus(str, Enum):
    """workflow 宿主状态。"""

    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class WorkflowStepSnapshot:
    """
    workflow 步骤摘要。

    参数：
    - step_id：步骤 ID
    - status：步骤状态
    - capability_id：可选能力 ID
    - error：可选错误信息
    """

    step_id: str
    status: str
    capability_id: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class WorkflowRunSnapshot:
    """
    workflow 运行摘要。

    参数：
    - run_id：运行 ID
    - workflow_id：workflow ID
    - workflow_instance_id：workflow 实例 ID
    - status：宿主状态
    - steps：步骤摘要列表
    - current_step_id：当前步骤 ID
    - waiting_approval_key：等待审批键
    - events_path：证据链 events 定位符
    """

    run_id: str
    workflow_id: str
    workflow_instance_id: str
    status: WorkflowRunStatus
    steps: list[WorkflowStepSnapshot] = field(default_factory=list)
    current_step_id: str | None = None
    waiting_approval_key: str | None = None
    events_path: str | None = None


@dataclass(frozen=True)
class WorkflowReplayRequest:
    """
    workflow replay 请求。

    参数：
    - workflow_id：workflow ID
    - run_id：宿主指定的 replay run ID
    - from_snapshot：可选上次运行快照
    - current_input：可选当前输入
    """

    workflow_id: str
    run_id: str
    from_snapshot: WorkflowRunSnapshot | None = None
    current_input: dict[str, Any] | None = None


def summarize_workflow_items(
    *,
    workflow_id: str,
    items: list[Any],
    terminal: CapabilityResult | None = None,
) -> WorkflowRunSnapshot:
    """
    从 workflow 轻量事件和 terminal result 收敛 WorkflowRunSnapshot。

    参数：
    - workflow_id：workflow ID
    - items：workflow 事件列表
    - terminal：可选终态结果
    """

    run_id = ""
    workflow_instance_id = ""
    current_step_id: str | None = None
    ordered_steps: list[str] = []
    steps: dict[str, WorkflowStepSnapshot] = {}
    final_status: WorkflowRunStatus = WorkflowRunStatus.RUNNING

    for item in items:
        if not isinstance(item, dict):
            continue
        typ = str(item.get("type") or "")
        if not run_id:
            run_id = str(item.get("run_id") or "")
        if typ == "workflow.started":
            workflow_instance_id = str(item.get("workflow_instance_id") or workflow_id)
            continue
        if typ == "workflow.step.started":
            step_id = str(item.get("step_id") or "").strip()
            if not step_id:
                continue
            current_step_id = step_id
            if step_id not in ordered_steps:
                ordered_steps.append(step_id)
            steps[step_id] = WorkflowStepSnapshot(
                step_id=step_id,
                status="running",
                capability_id=_optional_text(item.get("capability_id")),
            )
            continue
        if typ == "workflow.step.finished":
            step_id = str(item.get("step_id") or "").strip()
            if not step_id:
                continue
            if step_id not in ordered_steps:
                ordered_steps.append(step_id)
            status = str(item.get("status") or "pending").strip() or "pending"
            steps[step_id] = WorkflowStepSnapshot(
                step_id=step_id,
                status=status,
                capability_id=_optional_text(item.get("capability_id")),
                error=_optional_text(item.get("error")),
            )
            if status in {"running", "pending"}:
                current_step_id = step_id
            elif current_step_id == step_id:
                current_step_id = None
            continue
        if typ == "workflow.finished":
            final_status = _map_workflow_status_from_event(str(item.get("status") or "pending"))

    waiting_approval_key = None
    events_path = None
    if terminal is not None and terminal.node_report is not None:
        ticket = build_approval_ticket_from_report(terminal.node_report, capability_id=workflow_id)
        if ticket is not None:
            waiting_approval_key = ticket.approval_key
            final_status = WorkflowRunStatus.WAITING_HUMAN
            if ticket.step_id:
                current_step_id = ticket.step_id
        if isinstance(terminal.node_report.events_path, str) and terminal.node_report.events_path:
            events_path = terminal.node_report.events_path
        if not run_id:
            run_id = terminal.node_report.run_id

    if terminal is not None and final_status == WorkflowRunStatus.RUNNING:
        final_status = _map_workflow_status_from_terminal(terminal.status)

    if not run_id and terminal is not None:
        run_id = str(terminal.metadata.get("run_id") or "")
    if not workflow_instance_id:
        workflow_instance_id = workflow_id

    return WorkflowRunSnapshot(
        run_id=run_id,
        workflow_id=workflow_id,
        workflow_instance_id=workflow_instance_id,
        status=final_status,
        steps=[steps[step_id] for step_id in ordered_steps],
        current_step_id=current_step_id,
        waiting_approval_key=waiting_approval_key,
        events_path=events_path,
    )


def _map_workflow_status_from_event(status: str) -> WorkflowRunStatus:
    """把 workflow 事件状态归一为 WorkflowRunStatus。"""

    normalized = str(status or "").strip()
    if normalized == "success":
        return WorkflowRunStatus.COMPLETED
    if normalized == "failed":
        return WorkflowRunStatus.FAILED
    if normalized == "cancelled":
        return WorkflowRunStatus.CANCELLED
    return WorkflowRunStatus.RUNNING


def _map_workflow_status_from_terminal(status: CapabilityStatus) -> WorkflowRunStatus:
    """把 terminal CapabilityStatus 映射为 WorkflowRunStatus。"""

    if status == CapabilityStatus.SUCCESS:
        return WorkflowRunStatus.COMPLETED
    if status == CapabilityStatus.FAILED:
        return WorkflowRunStatus.FAILED
    if status == CapabilityStatus.CANCELLED:
        return WorkflowRunStatus.CANCELLED
    return WorkflowRunStatus.RUNNING


def _optional_text(value: Any) -> str | None:
    """把可选值归一为非空字符串。"""

    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
