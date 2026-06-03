from __future__ import annotations

from typing import Any

import pytest

from capability_runtime.config import RuntimeConfig
from capability_runtime.protocol.agent import AgentSpec
from capability_runtime.protocol.capability import CapabilityKind, CapabilityResult, CapabilitySpec, CapabilityStatus
from capability_runtime.runtime import Runtime
from capability_runtime.types import NodeReport, NodeToolCallReport
from capability_runtime.ui_events.projector import RuntimeUIEventProjector
from capability_runtime.ui_events.v1 import StreamLevel


def _agent(capability_id: str) -> AgentSpec:
    return AgentSpec(base=CapabilitySpec(id=capability_id, kind=CapabilityKind.AGENT, name=capability_id))


def test_workflow_step_ui_events_project_waiting_key_and_error() -> None:
    projector = RuntimeUIEventProjector(run_id="run-ui-wf", level=StreamLevel.UI)

    projected = projector.on_workflow_event(
        {
            "type": "workflow.step.finished",
            "run_id": "run-ui-wf",
            "workflow_id": "WF",
            "workflow_instance_id": "wf-1",
            "step_id": "review",
            "status": "needs_approval",
            "waiting_approval_key": "approval-step-ui",
            "error": "approval required",
        }
    )

    finished = [event for event in projected if event.type == "node.finished"]
    assert finished
    assert finished[-1].data["status"] == "needs_approval"
    assert finished[-1].data["waiting_approval_key"] == "approval-step-ui"
    assert finished[-1].data["error"] == "approval required"


@pytest.mark.asyncio
async def test_dynamic_dag_ui_events_project_waiting_key_and_error() -> None:
    def handler(_spec: AgentSpec, _input: dict[str, Any]) -> CapabilityResult:
        return CapabilityResult(
            status=CapabilityStatus.PENDING,
            error="approval required",
            error_code="NEEDS_APPROVAL",
            node_report=NodeReport(
                status="needs_approval",
                reason="approval_pending",
                completion_reason="needs_approval",
                run_id="run-dag-ui-waiting",
                tool_calls=[
                    NodeToolCallReport(
                        call_id="call-dag-ui",
                        name="review",
                        requires_approval=True,
                        approval_key="approval-dag-ui",
                    )
                ],
            ),
        )

    rt = Runtime(RuntimeConfig(mode="mock", mock_handler=handler))
    rt.register(_agent("agent.waiting"))
    plan = rt.compile_dynamic_workflow_plan(
        {"graph_id": "dag.ui.waiting", "tasks": [{"id": "waiting", "kind": "model", "binding": "agent.waiting"}]}
    )
    items = [item async for item in rt.run_dynamic_workflow_stream(plan)]
    workflow_events = [item for item in items if isinstance(item, dict)]

    projector = RuntimeUIEventProjector(run_id=workflow_events[0]["run_id"], level=StreamLevel.UI)
    projected = []
    for event in workflow_events:
        projected.extend(projector.on_workflow_event(event))

    finished = [
        event
        for event in projected
        if event.type == "node.finished"
        and any(segment.kind == "dynamic_node" and segment.id == "waiting" for segment in event.path)
    ]
    assert finished
    assert finished[-1].data["status"] == "needs_approval"
    assert finished[-1].data["waiting_approval_key"] == "approval-dag-ui"
    assert finished[-1].data["error"] == "approval required"


@pytest.mark.asyncio
async def test_dynamic_dag_runtime_stream_emits_additive_workflow_events_and_projected_node_paths() -> None:
    def handler(spec: AgentSpec, input: dict[str, Any]) -> dict[str, Any]:
        return {"capability_id": spec.base.id, "input": input}

    rt = Runtime(RuntimeConfig(mode="mock", mock_handler=handler))
    rt.register(_agent("agent.a"))
    rt.register(_agent("agent.b"))
    plan = rt.compile_dynamic_workflow_plan(
        {
            "graph_id": "dag.ui",
            "tasks": [
                {"id": "a", "kind": "model", "binding": "agent.a"},
                {"id": "b", "kind": "model", "binding": "agent.b", "depends_on": "a"},
            ],
        }
    )

    items: list[Any] = []
    async for item in rt.run_dynamic_workflow_stream(plan, input={"ui": True}):
        items.append(item)

    workflow_events = [item for item in items if isinstance(item, dict)]
    assert [event["type"] for event in workflow_events] == [
        "workflow.dynamic_dag.planned",
        "workflow.dynamic_dag.node.started",
        "workflow.dynamic_dag.node.finished",
        "workflow.dynamic_dag.node.started",
        "workflow.dynamic_dag.node.finished",
    ]
    assert all(event["workflow_instance_id"] for event in workflow_events)
    assert workflow_events[0]["graph_id"] == "dag.ui"
    assert workflow_events[1]["dag_node_id"] == "a"
    assert workflow_events[3]["dag_node_id"] == "b"

    projector = RuntimeUIEventProjector(run_id=workflow_events[0]["run_id"], level=StreamLevel.UI)
    projected = []
    for event in workflow_events:
        projected.extend(projector.on_workflow_event(event))

    assert any(event.type == "node.started" for event in projected)
    assert any(event.type == "node.finished" and event.data.get("status") == "success" for event in projected)
    dynamic_node_events = [
        event
        for event in projected
        if any(segment.kind == "dynamic_node" and segment.id in {"a", "b"} for segment in event.path)
    ]
    assert dynamic_node_events
    assert all(
        any(segment.kind == "workflow" and segment.instance_id for segment in event.path)
        for event in dynamic_node_events
    )
