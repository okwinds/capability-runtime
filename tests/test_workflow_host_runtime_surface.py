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
    assert [(step.step_id, step.status, step.capability_id) for step in snapshot.steps] == [
        ("draft", "success", "agent.draft"),
        ("review", "pending", "agent.review"),
    ]


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
async def test_replay_workflow_reexecutes_from_host_request_without_triggerflow_handle() -> None:
    """回归：replay_workflow 只接受 host request/snapshot，不要求宿主传内部 execution handle。"""

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

    assert result.status == CapabilityStatus.SUCCESS
    assert result.output == {"draft": {"handled_by": "agent.draft", "input": {}}}
