"""
05_dynamic_dag_preview：Dynamic DAG preview 的 runtime 契约示例。

运行：
  python examples/05_dynamic_dag_preview/run.py

本示例会编译 TaskDAG-like mapping 为本仓 `DynamicWorkflowPlan`，并通过
已注册 capability 执行一个最小 DAG 与一个 fan-out/fan-in 业务 DAG。
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
for path in (REPO_ROOT, SRC_ROOT):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec, Runtime, RuntimeConfig


def handler(spec: AgentSpec, input: Dict[str, Any], context=None) -> Any:
    """离线 handler：用于 Dynamic DAG 节点能力的确定性输出。"""

    _ = context
    if spec.base.id == "agent.dynamic.plan":
        return {"plan": ["draft", "review"], "topic": input.get("topic")}
    if spec.base.id == "agent.dynamic.write":
        deps = input.get("dependency_results") or {}
        return {"summary": f"dynamic summary for {deps.get('plan', {}).get('topic', 'unknown')}"}
    if spec.base.id == "agent.incident.context":
        return {"incident": input.get("incident"), "severity": "p1", "customer_impact": "checkout latency"}
    if spec.base.id == "agent.incident.security":
        deps = input.get("dependency_results") or {}
        return {"security": "no credential exposure", "source_severity": deps.get("context", {}).get("severity")}
    if spec.base.id == "agent.incident.reliability":
        deps = input.get("dependency_results") or {}
        return {"reliability": "backup queue mitigated", "source_severity": deps.get("context", {}).get("severity")}
    if spec.base.id == "agent.incident.comms":
        deps = input.get("dependency_results") or {}
        return {"comms": "tell account owners latency recovered and duplicate checks continue", "branches": sorted(deps)}
    return {"unknown_agent": spec.base.id, "input": input}


async def main() -> None:
    """编译并执行一个最小 Dynamic DAG preview。"""

    runtime = Runtime(RuntimeConfig(mode="mock", mock_handler=handler))
    runtime.register_many(
        [
            AgentSpec(
                base=CapabilitySpec(
                    id="agent.dynamic.plan",
                    kind=CapabilityKind.AGENT,
                    name="DynamicPlan",
                )
            ),
            AgentSpec(
                base=CapabilitySpec(
                    id="agent.dynamic.write",
                    kind=CapabilityKind.AGENT,
                    name="DynamicWrite",
                )
            ),
            AgentSpec(
                base=CapabilitySpec(
                    id="agent.incident.context",
                    kind=CapabilityKind.AGENT,
                    name="IncidentContext",
                )
            ),
            AgentSpec(
                base=CapabilitySpec(
                    id="agent.incident.security",
                    kind=CapabilityKind.AGENT,
                    name="IncidentSecurity",
                )
            ),
            AgentSpec(
                base=CapabilitySpec(
                    id="agent.incident.reliability",
                    kind=CapabilityKind.AGENT,
                    name="IncidentReliability",
                )
            ),
            AgentSpec(
                base=CapabilitySpec(
                    id="agent.incident.comms",
                    kind=CapabilityKind.AGENT,
                    name="IncidentComms",
                )
            ),
        ]
    )
    assert runtime.validate() == []

    task_dag_like = {
        "graph_id": "example.dynamic.preview",
        "tasks": [
            {
                "id": "plan",
                "kind": "agent",
                "title": "Plan",
                "binding": "agent.dynamic.plan",
                "inputs": {"topic": "runtime bridge upgrade"},
                "produces": ["plan"],
            },
            {
                "id": "write",
                "kind": "agent",
                "title": "Write",
                "depends_on": ["plan"],
                "binding": "agent.dynamic.write",
                "inputs": {"style": "brief"},
                "produces": ["summary"],
            },
        ],
    }

    plan = runtime.compile_dynamic_workflow_plan(task_dag_like)
    result = await runtime.run_dynamic_workflow(plan, input={"topic": "runtime bridge upgrade"})

    print("=== 05_dynamic_dag_preview ===")
    print("scenario=minimal")
    print(f"status={result.status.value}")
    print(f"output={result.output}")
    print(f"has_node_report={result.node_report is not None}")

    incident_dag_like = {
        "graph_id": "example.incident.briefing",
        "tasks": [
            {
                "id": "context",
                "kind": "agent",
                "title": "Collect incident context",
                "binding": "agent.incident.context",
                "inputs": {"incident": "payment webhook latency"},
                "produces": ["incident", "severity"],
            },
            {
                "id": "security",
                "kind": "agent",
                "title": "Security branch",
                "depends_on": ["context"],
                "binding": "agent.incident.security",
                "produces": ["security"],
            },
            {
                "id": "reliability",
                "kind": "agent",
                "title": "Reliability branch",
                "depends_on": ["context"],
                "binding": "agent.incident.reliability",
                "produces": ["reliability"],
            },
            {
                "id": "comms",
                "kind": "agent",
                "title": "Fan-in customer briefing",
                "depends_on": ["security", "reliability"],
                "binding": "agent.incident.comms",
                "produces": ["brief"],
            },
        ],
    }
    incident_plan = runtime.compile_dynamic_workflow_plan(incident_dag_like)
    incident_result = await runtime.run_dynamic_workflow(incident_plan, input={"incident": "payment webhook latency"})

    print("scenario=incident_fan_out_fan_in")
    print(f"incident_status={incident_result.status.value}")
    print(f"incident_output={incident_result.output}")
    print(f"incident_has_node_report={incident_result.node_report is not None}")


if __name__ == "__main__":
    asyncio.run(main())
