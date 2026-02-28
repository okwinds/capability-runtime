"""示例 05：带分支路由的条件工作流。"""
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
    ConditionalStep,
    ExecutionContext,
    InputMapping,
    RuntimeConfig,
    Step,
    WorkflowAdapter,
    WorkflowSpec,
)


class ConditionalDemoAgentAdapter:
    """用于条件路由示例的 mock Agent 适配器。"""

    async def execute(
        self,
        *,
        spec: AgentSpec,
        input: dict[str, Any],
        context: ExecutionContext,
        runtime: CapabilityRuntime,
    ) -> CapabilityResult:
        """为分类器与处理器返回可预测输出。"""
        _ = context
        _ = runtime
        agent_id = spec.base.id

        if agent_id == "agent.classifier":
            text = str(input.get("text", "")).lower()
            if "great" in text or "good" in text:
                category = "positive"
            elif "bad" in text or "issue" in text:
                category = "negative"
            else:
                category = "neutral"
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"category": category},
            )

        if agent_id == "agent.positive_handler":
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"route": "positive", "action": "celebrate"},
            )

        if agent_id == "agent.negative_handler":
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"route": "negative", "action": "investigate"},
            )

        if agent_id == "agent.neutral_handler":
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"route": "neutral", "action": "monitor"},
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
    """构建条件工作流，使用分支与默认路径。"""
    return WorkflowSpec(
        base=CapabilitySpec(
            id="workflow.conditional.demo",
            kind=CapabilityKind.WORKFLOW,
            name="Conditional Workflow Demo",
            description="ConditionalStep demo",
        ),
        steps=[
            Step(
                id="classify",
                capability=CapabilityRef(id="agent.classifier"),
                input_mappings=[InputMapping(source="context.text", target_field="text")],
            ),
            ConditionalStep(
                id="route",
                condition_source="step.classify.category",
                branches={
                    "positive": Step(
                        id="handle_positive",
                        capability=CapabilityRef(id="agent.positive_handler"),
                    ),
                    "negative": Step(
                        id="handle_negative",
                        capability=CapabilityRef(id="agent.negative_handler"),
                    ),
                },
                default=Step(
                    id="handle_neutral",
                    capability=CapabilityRef(id="agent.neutral_handler"),
                ),
            ),
        ],
    )


async def run_case(runtime: CapabilityRuntime, text: str) -> None:
    """执行单条输入用例，并打印分类结果与命中分支。"""
    result = await runtime.run("workflow.conditional.demo", input={"text": text})
    if result.status != CapabilityStatus.SUCCESS:
        raise RuntimeError(f"Workflow failed: {result.error}")

    print(f"text={text!r}")
    print(f"classified={result.output['classify']['category']}")
    print("route output:")
    print(pretty(result.output["route"]))
    print("---")


async def main() -> None:
    """执行两个用例，展示不同的条件路由结果。"""
    runtime = CapabilityRuntime(config=RuntimeConfig())
    runtime.set_adapter(CapabilityKind.AGENT, ConditionalDemoAgentAdapter())
    runtime.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())

    runtime.register_many(
        [
            build_agent("agent.classifier", "Classifier"),
            build_agent("agent.positive_handler", "Positive Handler"),
            build_agent("agent.negative_handler", "Negative Handler"),
            build_agent("agent.neutral_handler", "Neutral Handler"),
            build_workflow(),
        ]
    )

    missing = runtime.validate()
    if missing:
        raise RuntimeError(f"Missing capabilities: {missing}")

    print("=== 05 workflow_conditional ===")
    await run_case(runtime, "This draft is great.")
    await run_case(runtime, "Routine status update.")


if __name__ == "__main__":
    asyncio.run(main())
