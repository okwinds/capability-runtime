"""
04_triggerflow_orchestration：通过 capability-runtime 观察 workflow lifecycle。

运行：
  python examples/04_triggerflow_orchestration/run.py

说明：
- TriggerFlow 是 runtime 内部编排底座，不作为示例的下游公共 import 面。
- 本示例只使用 Runtime / WorkflowSpec，并打印宿主可读的 snapshot 摘要。
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

from capability_runtime import (
    AgentSpec,
    CapabilityKind,
    CapabilityRef,
    CapabilitySpec,
    InputMapping,
    Runtime,
    RuntimeConfig,
    Step,
    WorkflowSpec,
)


def handler(spec: AgentSpec, input: Dict[str, Any], context=None) -> Any:
    """离线 handler：固定输出，便于示例在无 key 环境中可回归。"""

    _ = context
    if spec.base.id == "agent.lifecycle.analyze":
        return {"analysis": f"why={input.get('topic')}", "risk": "low"}
    if spec.base.id == "agent.lifecycle.write":
        return {"summary": f"summary based on {input.get('analysis')}"}
    return {"unknown_agent": spec.base.id, "input": input}


async def main() -> None:
    """运行一个两步 workflow，并展示 lifecycle/snapshot 可读面。"""

    runtime = Runtime(RuntimeConfig(mode="mock", mock_handler=handler))
    runtime.register_many(
        [
            AgentSpec(
                base=CapabilitySpec(
                    id="agent.lifecycle.analyze",
                    kind=CapabilityKind.AGENT,
                    name="Analyze",
                    description="Analyze a topic.",
                )
            ),
            AgentSpec(
                base=CapabilitySpec(
                    id="agent.lifecycle.write",
                    kind=CapabilityKind.AGENT,
                    name="Write",
                    description="Write a short summary.",
                )
            ),
        ]
    )
    workflow = WorkflowSpec(
        base=CapabilitySpec(
            id="workflow.lifecycle.preview",
            kind=CapabilityKind.WORKFLOW,
            name="LifecyclePreview",
        ),
        steps=[
            Step(id="analyze", capability=CapabilityRef(id="agent.lifecycle.analyze")),
            Step(
                id="write",
                capability=CapabilityRef(id="agent.lifecycle.write"),
                input_mappings=[InputMapping(source="step.analyze.analysis", target_field="analysis")],
            ),
        ],
        output_mappings=[InputMapping(source="step.write.summary", target_field="summary")],
    )
    runtime.register(workflow)
    assert runtime.validate() == []

    items = []
    async for item in runtime.run_workflow_observable(
        "workflow.lifecycle.preview",
        input={"topic": "runtime workflow lifecycle"},
    ):
        items.append(item)

    snapshot = runtime.summarize_workflow_run(
        workflow_id="workflow.lifecycle.preview",
        items=items,
        terminal=items[-1] if items else None,
    )
    lifecycle_events = [
        item for item in items if isinstance(item, dict) and str(item.get("type", "")).startswith("workflow.lifecycle.")
    ]

    print("=== 04_triggerflow_orchestration ===")
    print(f"workflow_id={snapshot.workflow_id}")
    print(f"status={snapshot.status.value}")
    print(f"workflow_instance_id={snapshot.workflow_instance_id}")
    print(f"step_count={len(snapshot.steps)}")
    print(f"lifecycle_state={snapshot.lifecycle_state}")
    print(f"execution_id={snapshot.execution_id}")
    print(f"state_version={snapshot.state_version}")
    print(f"intervention_mode={snapshot.intervention_mode}")
    print(f"pending_interventions={len(snapshot.pending_interventions)}")
    print(f"close_reason={snapshot.close_reason}")
    print(f"lifecycle_event_count={len(lifecycle_events)}")
    print("lifecycle_fields=additive")


if __name__ == "__main__":
    asyncio.run(main())
