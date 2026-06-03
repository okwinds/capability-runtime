from __future__ import annotations

from typing import Any

import pytest

from capability_runtime import (
    AgentSpec,
    CapabilityKind,
    CapabilityRef,
    CapabilitySpec,
    Runtime,
    RuntimeConfig,
    Step,
    WorkflowReplayRequest,
    WorkflowRunSnapshot,
    WorkflowRunStatus,
    WorkflowSpec,
)
from capability_runtime.protocol.capability import CapabilityResult, CapabilityStatus
from capability_runtime.types import NodeReport, NodeToolCallReport


def _build_runtime() -> Runtime:
    """构造用于 workflow host surface 回归的离线 Runtime。"""

    return Runtime(
        RuntimeConfig(
            mode="mock",
            mock_handler=lambda spec, input, context=None: CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"handled_by": spec.base.id, "input": dict(input)},
                metadata={"run_id": getattr(context, "run_id", None)},
            ),
        )
    )


def _waiting_terminal() -> CapabilityResult:
    """构造 workflow waiting approval 终态。"""

    return CapabilityResult(
        status=CapabilityStatus.PENDING,
        node_report=NodeReport(
            status="needs_approval",
            reason="tool_requires_approval",
            completion_reason="needs_approval",
            run_id="wf-run-1",
            events_path="/tmp/wf-run-1.jsonl",
            tool_calls=[
                NodeToolCallReport(
                    call_id="call-1",
                    name="apply_patch",
                    requires_approval=True,
                    approval_key="approval-1",
                    ok=False,
                )
            ],
            meta={"step_id": "review"},
        ),
        metadata={"run_id": "wf-run-1"},
    )


def test_summarize_workflow_run_collects_step_statuses_and_waiting_approval() -> None:
    """回归：workflow summary 需要收敛 instance/steps/current/waiting_approval_key。"""

    rt = _build_runtime()
    items: list[Any] = [
        {
            "type": "workflow.started",
            "run_id": "wf-run-1",
            "workflow_id": "wf.review",
            "workflow_instance_id": "wf-inst-1",
        },
        {
            "type": "workflow.step.started",
            "run_id": "wf-run-1",
            "workflow_id": "wf.review",
            "workflow_instance_id": "wf-inst-1",
            "step_id": "draft",
            "capability_id": "agent.draft",
        },
        {
            "type": "workflow.step.finished",
            "run_id": "wf-run-1",
            "workflow_id": "wf.review",
            "workflow_instance_id": "wf-inst-1",
            "step_id": "draft",
            "capability_id": "agent.draft",
            "status": "success",
        },
        {
            "type": "workflow.step.started",
            "run_id": "wf-run-1",
            "workflow_id": "wf.review",
            "workflow_instance_id": "wf-inst-1",
            "step_id": "review",
            "capability_id": "agent.review",
        },
        {
            "type": "workflow.step.finished",
            "run_id": "wf-run-1",
            "workflow_id": "wf.review",
            "workflow_instance_id": "wf-inst-1",
            "step_id": "review",
            "capability_id": "agent.review",
            "status": "pending",
            "error": None,
        },
    ]

    snapshot = rt.summarize_workflow_run(
        workflow_id="wf.review",
        items=items,
        terminal=_waiting_terminal(),
    )

    assert isinstance(snapshot, WorkflowRunSnapshot)
    assert snapshot.run_id == "wf-run-1"
    assert snapshot.workflow_id == "wf.review"
    assert snapshot.workflow_instance_id == "wf-inst-1"
    assert snapshot.status == WorkflowRunStatus.WAITING_HUMAN
    assert snapshot.current_step_id == "review"
    assert snapshot.waiting_approval_key == "approval-1"
    assert snapshot.events_path == "/tmp/wf-run-1.jsonl"
    assert snapshot.host_runtime == {
        "status": "waiting_human",
        "wait_kind": "approval",
        "run_id": "wf-run-1",
        "node_status": "needs_approval",
        "events_path": "/tmp/wf-run-1.jsonl",
        "tool_name": "apply_patch",
        "call_id": "call-1",
        "workflow_id": None,
        "workflow_instance_id": None,
        "step_id": "review",
        "approval_key": "approval-1",
        "message_kind": "approval_message",
        "message_preview": None,
        "resume_state": {"waiting_approval_key": "approval-1"},
    }
    assert [(step.step_id, step.status, step.capability_id) for step in snapshot.steps] == [
        ("draft", "success", "agent.draft"),
        ("review", "pending", "agent.review"),
    ]


def test_summarize_workflow_run_event_only_waiting_approval() -> None:
    """仅持久化 workflow events 时也应还原 WAITING_HUMAN 与 approval key。"""

    rt = _build_runtime()
    snapshot = rt.summarize_workflow_run(
        workflow_id="wf.review",
        items=[
            {
                "type": "workflow.started",
                "run_id": "wf-run-2",
                "workflow_id": "wf.review",
                "workflow_instance_id": "wf-inst-2",
            },
            {
                "type": "workflow.step.started",
                "run_id": "wf-run-2",
                "workflow_id": "wf.review",
                "workflow_instance_id": "wf-inst-2",
                "step_id": "review",
                "capability_id": "agent.review",
            },
            {
                "type": "workflow.step.finished",
                "run_id": "wf-run-2",
                "workflow_id": "wf.review",
                "workflow_instance_id": "wf-inst-2",
                "step_id": "review",
                "capability_id": "agent.review",
                "status": "pending",
                "waiting_approval_key": "approval-event-1",
            },
        ],
        terminal=None,
    )

    assert snapshot.status == WorkflowRunStatus.WAITING_HUMAN
    assert snapshot.current_step_id == "review"
    assert snapshot.waiting_approval_key == "approval-event-1"


def test_summarize_workflow_run_event_only_pending_finished_is_waiting_human() -> None:
    """workflow.finished status=pending 不能被 event-only snapshot 误判为 running。"""

    rt = _build_runtime()
    snapshot = rt.summarize_workflow_run(
        workflow_id="wf.review",
        items=[
            {
                "type": "workflow.started",
                "run_id": "wf-run-pending",
                "workflow_id": "wf.review",
                "workflow_instance_id": "wf-inst-pending",
            },
            {
                "type": "workflow.finished",
                "run_id": "wf-run-pending",
                "workflow_id": "wf.review",
                "workflow_instance_id": "wf-inst-pending",
                "status": "pending",
                "waiting_approval_key": "approval-finished-1",
            },
        ],
        terminal=None,
    )

    assert snapshot.status == WorkflowRunStatus.WAITING_HUMAN
    assert snapshot.waiting_approval_key == "approval-finished-1"


@pytest.mark.asyncio
async def test_summarize_dynamic_workflow_run_collects_dag_nodes_as_steps() -> None:
    """Dynamic DAG events must project into the same host WorkflowRunSnapshot surface."""

    rt = _build_runtime()
    rt.register(AgentSpec(base=CapabilitySpec(id="agent.first", kind=CapabilityKind.AGENT, name="First")))
    rt.register(AgentSpec(base=CapabilitySpec(id="agent.second", kind=CapabilityKind.AGENT, name="Second")))

    plan = rt.compile_dynamic_workflow_plan(
        {
            "graph_id": "dag.runtime",
            "tasks": [
                {"id": "first", "kind": "model", "binding": "agent.first"},
                {"id": "second", "kind": "model", "binding": "agent.second", "depends_on": "first"},
            ],
        }
    )
    items = [item async for item in rt.run_dynamic_workflow_stream(plan, input={"topic": "snapshot"})]
    terminal = next(item for item in items if isinstance(item, CapabilityResult))
    workflow_events = [item for item in items if isinstance(item, dict)]

    snapshot = rt.summarize_workflow_run(
        workflow_id="dag.runtime",
        items=workflow_events,
        terminal=terminal,
    )

    assert snapshot.workflow_instance_id.startswith("dynamic-dag:")
    assert snapshot.workflow_instance_id.endswith(":dag.runtime")
    assert snapshot.status == WorkflowRunStatus.COMPLETED
    assert [(step.step_id, step.status, step.capability_id) for step in snapshot.steps] == [
        ("first", "success", "agent.first"),
        ("second", "success", "agent.second"),
    ]


def test_summarize_dynamic_workflow_run_waiting_approval_preserves_current_node() -> None:
    """Dynamic DAG needs_approval 节点应成为 host snapshot 的当前阻塞节点。"""

    rt = _build_runtime()
    terminal = CapabilityResult(
        status=CapabilityStatus.PENDING,
        error_code="DYNAMIC_DAG_NODE_NEEDS_APPROVAL",
        node_report=NodeReport(
            status="needs_approval",
            reason="approval_pending",
            completion_reason="approval_pending",
            run_id="dag-run-approval",
            tool_calls=[
                NodeToolCallReport(
                    call_id="call-dag",
                    name="review",
                    requires_approval=True,
                    approval_key="approval-dag-1",
                    ok=False,
                )
            ],
            meta={
                "dynamic_dag": {
                    "graph_id": "dag.approval",
                    "plan_hash": "hash",
                    "node_count": 1,
                    "source": "task_dag",
                    "nodes": {
                        "approval": {
                            "id": "approval",
                            "status": "needs_approval",
                            "capability_id": "agent.approval",
                        }
                    },
                    "waiting": {
                        "dag_node_id": "approval",
                        "approval_key": "approval-dag-1",
                    },
                }
            },
        ),
    )

    snapshot = rt.summarize_workflow_run(
        workflow_id="dag.approval",
        items=[
            {
                "type": "workflow.dynamic_dag.planned",
                "run_id": "dag-run-approval",
                "workflow_id": "dag.approval",
                "workflow_instance_id": "dynamic-dag:dag-run-approval:dag.approval",
            },
            {
                "type": "workflow.dynamic_dag.node.started",
                "run_id": "dag-run-approval",
                "workflow_id": "dag.approval",
                "workflow_instance_id": "dynamic-dag:dag-run-approval:dag.approval",
                "dag_node_id": "approval",
                "capability_id": "agent.approval",
            },
            {
                "type": "workflow.dynamic_dag.node.finished",
                "run_id": "dag-run-approval",
                "workflow_id": "dag.approval",
                "workflow_instance_id": "dynamic-dag:dag-run-approval:dag.approval",
                "dag_node_id": "approval",
                "capability_id": "agent.approval",
                "status": "needs_approval",
                "waiting_approval_key": "approval-dag-1",
            },
        ],
        terminal=terminal,
    )

    assert snapshot.status == WorkflowRunStatus.WAITING_HUMAN
    assert snapshot.current_step_id == "approval"
    assert snapshot.waiting_approval_key == "approval-dag-1"


@pytest.mark.asyncio
async def test_run_workflow_observable_yields_workflow_events_and_terminal() -> None:
    """回归：宿主可直接消费 workflow observable，而不是自己分流 mixed stream。"""

    rt = _build_runtime()
    rt.register(AgentSpec(base=CapabilitySpec(id="agent.draft", kind=CapabilityKind.AGENT, name="Draft Agent")))
    rt.register(
        WorkflowSpec(
            base=CapabilitySpec(id="wf.observable", kind=CapabilityKind.WORKFLOW, name="Observable Workflow"),
            steps=[Step(id="draft", capability=CapabilityRef(id="agent.draft"))],
        )
    )

    items = [item async for item in rt.run_workflow_observable("wf.observable", input={"topic": "x"})]

    assert any(isinstance(item, dict) and item.get("type") == "workflow.started" for item in items)
    assert any(isinstance(item, dict) and item.get("type") == "workflow.finished" for item in items)
    terminal = next(item for item in items if isinstance(item, CapabilityResult))
    assert terminal.status == CapabilityStatus.SUCCESS


@pytest.mark.asyncio
async def test_replay_workflow_from_snapshot_fails_closed_until_snapshot_replay_is_supported() -> None:
    """from_snapshot 不能被静默当作从头 rerun，否则会重复已完成步骤副作用。"""

    rt = _build_runtime()
    rt.register(AgentSpec(base=CapabilitySpec(id="agent.draft", kind=CapabilityKind.AGENT, name="Draft Agent")))
    rt.register(
        WorkflowSpec(
            base=CapabilitySpec(id="wf.replay", kind=CapabilityKind.WORKFLOW, name="Replay Workflow"),
            steps=[Step(id="draft", capability=CapabilityRef(id="agent.draft"))],
        )
    )

    snapshot = WorkflowRunSnapshot(
        run_id="wf-run-replay",
        workflow_id="wf.replay",
        workflow_instance_id="wf-inst-replay",
        status=WorkflowRunStatus.RUNNING,
        current_step_id="draft",
    )
    result = await rt.replay_workflow(
        WorkflowReplayRequest(
            workflow_id="wf.replay",
            run_id="wf-run-replay",
            from_snapshot=snapshot,
            current_input={"topic": "retry"},
        )
    )

    assert result.status == CapabilityStatus.FAILED
    assert result.error_code == "WORKFLOW_SNAPSHOT_REPLAY_UNSUPPORTED"
