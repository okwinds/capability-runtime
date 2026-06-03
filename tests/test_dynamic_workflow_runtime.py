from __future__ import annotations

from typing import Any

import pytest

from capability_runtime import NodeReport
from capability_runtime.config import RuntimeConfig
from capability_runtime.host_protocol import HostRunStatus
from capability_runtime.protocol.agent import AgentSpec
from capability_runtime.protocol.capability import CapabilityKind, CapabilityResult, CapabilitySpec, CapabilityStatus
from capability_runtime.runtime import Runtime
from capability_runtime.types import NodeToolCallReport, NodeUsageReport


def _agent(capability_id: str) -> AgentSpec:
    return AgentSpec(base=CapabilitySpec(id=capability_id, kind=CapabilityKind.AGENT, name=capability_id))


@pytest.mark.asyncio
async def test_run_dynamic_workflow_executes_registered_capabilities_and_injects_dependency_results() -> None:
    seen_inputs: dict[str, dict[str, Any]] = {}

    def handler(spec: AgentSpec, input: dict[str, Any]) -> CapabilityResult:
        seen_inputs[spec.base.id] = input
        suffix = spec.base.id.rsplit(".", 1)[-1]
        report = NodeReport(
            status="success",
            completion_reason="run_completed",
            run_id=f"run-{suffix}",
            events_path=f"wal://dynamic-{suffix}",
            usage=NodeUsageReport(model="dynamic-model", input_tokens=1, output_tokens=2, total_tokens=3),
            tool_calls=[NodeToolCallReport(call_id=f"call-{suffix}", name="lookup", ok=True)],
            artifacts=[f"runtime-action://dynamic-{suffix}"],
        )
        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output={"capability_id": spec.base.id, "input": input},
            report=report,
            node_report=report,
        )

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
    assert result.node_report.events_path == "wal://dynamic-second"
    assert result.node_report.usage is not None
    assert result.node_report.usage.total_tokens == 6
    assert [call.call_id for call in result.node_report.tool_calls] == ["call-first", "call-second"]
    assert result.node_report.artifacts == ["runtime-action://dynamic-first", "runtime-action://dynamic-second"]
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("node_result", "expected_result_status", "expected_node_status", "expected_error_code"),
    [
        (
            CapabilityResult(status=CapabilityStatus.PENDING, error="waiting approval"),
            CapabilityStatus.PENDING,
            "pending",
            "DYNAMIC_DAG_NODE_PENDING",
        ),
        (
            CapabilityResult(status=CapabilityStatus.CANCELLED, error="cancelled"),
            CapabilityStatus.CANCELLED,
            "cancelled",
            "DYNAMIC_DAG_NODE_CANCELLED",
        ),
    ],
)
async def test_run_dynamic_workflow_preserves_non_failed_terminal_node_statuses(
    node_result: CapabilityResult,
    expected_result_status: CapabilityStatus,
    expected_node_status: str,
    expected_error_code: str,
) -> None:
    """Dynamic DAG 不能把 pending/cancelled 等可区分状态压平成 failed。"""

    def handler(spec: AgentSpec, input: dict[str, Any]) -> CapabilityResult:
        _ = (spec, input)
        return node_result

    rt = Runtime(RuntimeConfig(mode="mock", mock_handler=handler))
    rt.register(_agent("agent.gated"))

    result = await rt.run_dynamic_workflow(
        {
            "graph_id": "dag.nonfailed",
            "tasks": [{"id": "gated", "kind": "model", "binding": "agent.gated"}],
        }
    )

    assert result.status == expected_result_status
    assert result.error_code == expected_error_code
    assert result.node_report is not None
    assert result.node_report.meta["dynamic_dag"]["nodes"]["gated"]["status"] == expected_node_status


@pytest.mark.asyncio
async def test_run_dynamic_workflow_preserves_needs_approval_node_report_status() -> None:
    """节点 NodeReport 已进入 needs_approval 时，DAG 摘要和终态也应保留该语义。"""

    def handler(spec: AgentSpec, input: dict[str, Any]) -> CapabilityResult:
        _ = (spec, input)
        return CapabilityResult(
            status=CapabilityStatus.PENDING,
            error="approval required",
            node_report=NodeReport(
                status="needs_approval",
                reason="approval_pending",
                completion_reason="needs_approval",
                run_id="run-approval",
                events_path="wal://dynamic-approval",
                tool_calls=[
                    NodeToolCallReport(
                        call_id="call-approval",
                        name="review",
                        requires_approval=True,
                        approval_key="approval-dag-terminal",
                    )
                ],
                meta={"approval_requested_at_ms": 456},
            ),
        )

    rt = Runtime(RuntimeConfig(mode="mock", mock_handler=handler))
    rt.register(_agent("agent.approval"))

    result = await rt.run_dynamic_workflow(
        {
            "graph_id": "dag.approval",
            "tasks": [{"id": "approval", "kind": "model", "binding": "agent.approval"}],
        }
    )

    assert result.status == CapabilityStatus.PENDING
    assert result.error_code == "DYNAMIC_DAG_NODE_NEEDS_APPROVAL"
    assert result.node_report is not None
    assert result.node_report.status == "needs_approval"
    assert result.node_report.events_path == "wal://dynamic-approval"
    assert result.node_report.tool_calls[0].approval_key == "approval-dag-terminal"
    assert result.node_report.meta["dynamic_dag"]["nodes"]["approval"]["status"] == "needs_approval"
    ticket = rt.build_approval_ticket(result, capability_id="dag.approval")
    snapshot = rt.summarize_host_run(result, capability_id="dag.approval")
    assert ticket is not None
    assert ticket.approval_key == "approval-dag-terminal"
    assert ticket.created_at_ms == 456
    assert snapshot.status == HostRunStatus.WAITING_HUMAN
    assert snapshot.approval_ticket is not None
    assert snapshot.approval_ticket.approval_key == "approval-dag-terminal"
    assert snapshot.events_path == "wal://dynamic-approval"


@pytest.mark.asyncio
async def test_run_dynamic_workflow_stream_emits_waiting_approval_key_on_node_finished() -> None:
    """Dynamic DAG 事件流自身要携带 waiting evidence，不能只靠 terminal NodeReport 补偿。"""

    def handler(spec: AgentSpec, input: dict[str, Any]) -> CapabilityResult:
        _ = (spec, input)
        return CapabilityResult(
            status=CapabilityStatus.PENDING,
            error="approval required",
            node_report=NodeReport(
                status="needs_approval",
                reason="approval_pending",
                completion_reason="needs_approval",
                run_id="run-approval",
                tool_calls=[
                    NodeToolCallReport(
                        call_id="call-approval",
                        name="review",
                        requires_approval=True,
                        approval_key="approval-dag-stream",
                    )
                ],
            ),
        )

    rt = Runtime(RuntimeConfig(mode="mock", mock_handler=handler))
    rt.register(_agent("agent.approval"))
    plan = rt.compile_dynamic_workflow_plan(
        {
            "graph_id": "dag.approval.stream",
            "tasks": [{"id": "approval", "kind": "model", "binding": "agent.approval"}],
        }
    )

    items = [item async for item in rt.run_dynamic_workflow_stream(plan)]
    finished = [
        item
        for item in items
        if isinstance(item, dict)
        and item.get("type") == "workflow.dynamic_dag.node.finished"
        and item.get("dag_node_id") == "approval"
    ]

    assert finished
    assert finished[-1]["status"] == "needs_approval"
    assert finished[-1]["waiting_approval_key"] == "approval-dag-stream"
    assert finished[-1]["error"] == "approval required"
