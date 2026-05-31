from __future__ import annotations

from typing import Any

import pytest

from capability_runtime.config import RuntimeConfig
from capability_runtime.protocol.agent import AgentSpec
from capability_runtime.protocol.capability import CapabilityKind, CapabilitySpec
from capability_runtime.runtime import Runtime
from capability_runtime.ui_events.projector import RuntimeUIEventProjector
from capability_runtime.ui_events.v1 import StreamLevel


def _agent(capability_id: str) -> AgentSpec:
    return AgentSpec(base=CapabilitySpec(id=capability_id, kind=CapabilityKind.AGENT, name=capability_id))


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
