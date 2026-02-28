"""
02_workflow：顺序 + 循环 + 条件分支（离线 mock）。

运行：
  python examples/02_workflow/run.py
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from capability_runtime import (
    AgentSpec,
    CapabilityRef,
    CapabilityKind,
    CapabilitySpec,
    ConditionalStep,
    InputMapping,
    LoopStep,
    Runtime,
    RuntimeConfig,
    Step,
    WorkflowSpec,
)


def handler(spec: AgentSpec, input: Dict[str, Any], context=None) -> Any:
    """mock_handler：根据 spec.id 产出确定性输出，便于演示数据流与分支选择。"""

    _ = context

    if spec.base.id == "agent.generate":
        return {"items": [{"name": "apple"}, {"name": "banana"}], "category": "positive"}
    if spec.base.id == "agent.process_item":
        name = str(input.get("item_name", ""))
        return {"name": name, "upper": name.upper()}
    if spec.base.id == "agent.summarize_positive":
        processed = input.get("processed") or []
        return {"summary": f"处理完成（positive）：{len(processed)} items"}
    if spec.base.id == "agent.summarize_default":
        return {"summary": "默认分支（default）"}

    return {"unknown_agent": spec.base.id, "input": input}


async def main() -> None:
    """构造并运行一个包含 Step/Loop/Conditional 的 Workflow。"""

    rt = Runtime(RuntimeConfig(mode="mock", mock_handler=handler))

    rt.register_many(
        [
            AgentSpec(base=CapabilitySpec(id="agent.generate", kind=CapabilityKind.AGENT, name="Generate")),
            AgentSpec(base=CapabilitySpec(id="agent.process_item", kind=CapabilityKind.AGENT, name="ProcessItem")),
            AgentSpec(
                base=CapabilitySpec(
                    id="agent.summarize_positive",
                    kind=CapabilityKind.AGENT,
                    name="SummarizePositive",
                )
            ),
            AgentSpec(
                base=CapabilitySpec(
                    id="agent.summarize_default",
                    kind=CapabilityKind.AGENT,
                    name="SummarizeDefault",
                )
            ),
        ]
    )

    wf = WorkflowSpec(
        base=CapabilitySpec(id="wf.demo", kind=CapabilityKind.WORKFLOW, name="DemoWorkflow"),
        steps=[
            Step(id="generate", capability=CapabilityRef(id="agent.generate")),
            LoopStep(
                id="process",
                capability=CapabilityRef(id="agent.process_item"),
                iterate_over="step.generate.items",
                item_input_mappings=[InputMapping(source="item.name", target_field="item_name")],
            ),
            ConditionalStep(
                id="route",
                condition_source="step.generate.category",
                branches={
                    "positive": Step(
                        id="summary",
                        capability=CapabilityRef(id="agent.summarize_positive"),
                        input_mappings=[InputMapping(source="step.process", target_field="processed")],
                    )
                },
                default=Step(
                    id="summary_default",
                    capability=CapabilityRef(id="agent.summarize_default"),
                ),
            ),
        ],
        output_mappings=[
            InputMapping(source="step.generate.items", target_field="items"),
            InputMapping(source="step.process", target_field="processed"),
            InputMapping(source="step.summary.summary", target_field="summary"),
        ],
    )
    rt.register(wf)
    assert rt.validate() == []

    res = await rt.run("wf.demo", input={})
    print("=== 02_workflow ===")
    print(f"status={res.status.value}")
    print(f"output={res.output}")


if __name__ == "__main__":
    asyncio.run(main())
