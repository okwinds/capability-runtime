from __future__ import annotations

from typing import Any

import pytest

from capability_runtime.config import RuntimeConfig
from capability_runtime.protocol.agent import AgentSpec
from capability_runtime.protocol.capability import CapabilityKind, CapabilityResult, CapabilitySpec, CapabilityStatus
from capability_runtime.runtime import Runtime


def _agent(capability_id: str) -> AgentSpec:
    return AgentSpec(base=CapabilitySpec(id=capability_id, kind=CapabilityKind.AGENT, name=capability_id))


@pytest.mark.asyncio
async def test_run_dynamic_workflow_executes_registered_capabilities_and_injects_dependency_results() -> None:
    seen_inputs: dict[str, dict[str, Any]] = {}

    def handler(spec: AgentSpec, input: dict[str, Any]) -> dict[str, Any]:
        seen_inputs[spec.base.id] = input
        return {"capability_id": spec.base.id, "input": input}

    rt = Runtime(RuntimeConfig(mode="mock", mock_handler=handler))
    rt.register(_agent("agent.first"))
    rt.register(_agent("agent.second"))

    plan = rt.compile_dynamic_workflow_plan(
        {
            "graph_id": "dag.runtime",
            "tasks": [
                {"id": "first", "kind": "model", "binding": "agent.first", "inputs": {"topic": "runtime"}},
                {"id": "second", "kind": "skill", "binding": "agent.second", "depends_on": "first", "inputs": {"mode": "review"}},
            ],
        }
    )

    result = await rt.run_dynamic_workflow(plan, input={"request_id": "req-1"})

    assert result.status == CapabilityStatus.SUCCESS
    assert result.output["graph_id"] == "dag.runtime"
    assert result.output["nodes"]["first"]["status"] == "success"
    assert result.output["nodes"]["second"]["status"] == "success"
    assert seen_inputs["agent.first"]["topic"] == "runtime"
    assert seen_inputs["agent.first"]["workflow_input"] == {"request_id": "req-1"}
    assert seen_inputs["agent.second"]["dependency_results"]["first"]["capability_id"] == "agent.first"

    assert result.node_report is not None
    dynamic_meta = result.node_report.meta["dynamic_dag"]
    assert dynamic_meta["graph_id"] == "dag.runtime"
    assert dynamic_meta["plan_hash"] == plan.plan_hash
    assert dynamic_meta["node_count"] == 2
    assert dynamic_meta["source"] == "task_dag"
    assert dynamic_meta["nodes"]["first"]["capability_id"] == "agent.first"
    assert dynamic_meta["nodes"]["second"]["depends_on"] == ["first"]


@pytest.mark.asyncio
async def test_run_dynamic_workflow_returns_fail_closed_for_unresolved_node() -> None:
    rt = Runtime(RuntimeConfig(mode="mock"))

    result = await rt.run_dynamic_workflow(
        {
            "graph_id": "dag.unresolved",
            "tasks": [{"id": "missing", "kind": "model", "binding": "agent.missing"}],
        }
    )

    assert result.status == CapabilityStatus.FAILED
    assert result.error_code == "DYNAMIC_DAG_NODE_UNRESOLVED"
    assert result.node_report is not None
    assert result.node_report.meta["dynamic_dag"]["graph_id"] == "dag.unresolved"


@pytest.mark.asyncio
async def test_run_dynamic_workflow_fail_fast_marks_dependents_skipped() -> None:
    def handler(spec: AgentSpec, input: dict[str, Any]) -> Any:
        if spec.base.id == "agent.fail":
            return CapabilityResult(status=CapabilityStatus.FAILED, error="boom", error_code="BOOM")
        return {"capability_id": spec.base.id, "input": input}

    rt = Runtime(RuntimeConfig(mode="mock", mock_handler=handler))
    rt.register(_agent("agent.fail"))
    rt.register(_agent("agent.after"))
    rt.register(_agent("agent.independent"))

    result = await rt.run_dynamic_workflow(
        {
            "graph_id": "dag.fail-fast",
            "tasks": [
                {"id": "bad", "kind": "model", "binding": "agent.fail"},
                {"id": "after", "kind": "model", "binding": "agent.after", "depends_on": "bad"},
                {"id": "independent", "kind": "model", "binding": "agent.independent"},
            ],
        }
    )

    assert result.status == CapabilityStatus.FAILED
    assert result.error_code == "DYNAMIC_DAG_NODE_FAILED"
    assert result.node_report is not None
    nodes = result.node_report.meta["dynamic_dag"]["nodes"]
    assert nodes["bad"]["status"] == "failed"
    assert nodes["after"]["status"] == "skipped"
    assert nodes["after"]["skip_reason"] == "dependency_failed"
    assert nodes["independent"]["status"] == "success"
