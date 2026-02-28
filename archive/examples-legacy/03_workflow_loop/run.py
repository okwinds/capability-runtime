"""示例 03：使用 LoopStep 与 item 映射的循环工作流。"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from capability_runtime import (
    AgentSpec,
    CapabilityKind,
    CapabilityRef,
    CapabilityResult,
    CapabilityRuntime,
    CapabilitySpec,
    CapabilityStatus,
    ExecutionContext,
    InputMapping,
    LoopStep,
    RuntimeConfig,
    Step,
    WorkflowAdapter,
    WorkflowSpec,
)


class LoopDemoAgentAdapter:
    """用于循环工作流示例的 mock Agent 适配器。"""

    async def execute(
        self,
        *,
        spec: AgentSpec,
        input: dict[str, Any],
        context: ExecutionContext,
        runtime: CapabilityRuntime,
    ) -> CapabilityResult:
        """返回可预测的列表生成与条目处理结果。"""
        _ = context
        _ = runtime
        agent_id = spec.base.id

        if agent_id == "agent.list_generator":
            category = str(input.get("category", "general"))
            items = [
                {"name": f"{category}-alpha"},
                {"name": f"{category}-beta"},
                {"name": f"{category}-gamma"},
            ]
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"items": items},
            )

        if agent_id == "agent.item_processor":
            item_name = str(input.get("item_name", "unknown"))
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={
                    "item_name": item_name,
                    "processed": f"{item_name.upper()}_PROCESSED",
                },
            )

        return CapabilityResult(
            status=CapabilityStatus.FAILED,
            error=f"Unsupported agent id: {agent_id}",
        )


def pretty(data: Any) -> str:
    """将 JSON 输出格式化为便于终端阅读的文本。"""
    return json.dumps(data, ensure_ascii=False, indent=2)


def build_agent(agent_id: str, name: str) -> AgentSpec:
    """根据 id 与名称构建最小化的 Agent 规格。"""
    return AgentSpec(
        base=CapabilitySpec(
            id=agent_id,
            kind=CapabilityKind.AGENT,
            name=name,
            description=f"Offline mock agent: {name}",
        )
    )


def build_workflow() -> WorkflowSpec:
    """构建循环工作流，演示 iterate_over 与 item.name 映射。"""
    return WorkflowSpec(
        base=CapabilitySpec(
            id="workflow.loop.demo",
            kind=CapabilityKind.WORKFLOW,
            name="Loop Workflow Demo",
            description="LoopStep demo",
        ),
        steps=[
            Step(
                id="generate",
                capability=CapabilityRef(id="agent.list_generator"),
                input_mappings=[
                    InputMapping(source="context.category", target_field="category")
                ],
            ),
            LoopStep(
                id="process_items",
                capability=CapabilityRef(id="agent.item_processor"),
                iterate_over="step.generate.items",
                item_input_mappings=[
                    InputMapping(source="item.name", target_field="item_name")
                ],
                max_iterations=20,
            ),
        ],
    )


async def main() -> None:
    """执行循环工作流并打印每个条目的输出。"""
    runtime = CapabilityRuntime(config=RuntimeConfig())
    runtime.set_adapter(CapabilityKind.AGENT, LoopDemoAgentAdapter())
    runtime.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())

    runtime.register_many(
        [
            build_agent("agent.list_generator", "List Generator"),
            build_agent("agent.item_processor", "Item Processor"),
            build_workflow(),
        ]
    )

    missing = runtime.validate()
    if missing:
        raise RuntimeError(f"Missing capabilities: {missing}")

    result = await runtime.run("workflow.loop.demo", input={"category": "task"})
    if result.status != CapabilityStatus.SUCCESS:
        raise RuntimeError(f"Workflow failed: {result.error}")

    loop_results = result.output["process_items"]
    print("=== 03 workflow_loop ===")
    print(f"workflow.status={result.status.value}")
    print("generated.items:")
    print(pretty(result.output["generate"]["items"]))
    print("loop results:")
    for index, item_result in enumerate(loop_results):
        print(f"- item[{index}]")
        print(pretty(item_result))


if __name__ == "__main__":
    asyncio.run(main())
