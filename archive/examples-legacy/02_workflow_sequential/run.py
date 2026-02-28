"""示例 02：使用 Step 与 InputMapping 的顺序工作流。"""
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
    RuntimeConfig,
    Step,
    WorkflowAdapter,
    WorkflowSpec,
)


class SequentialDemoAgentAdapter:
    """用于顺序工作流演示的 mock Agent 适配器，输出可预测。"""

    async def execute(
        self,
        *,
        spec: AgentSpec,
        input: dict[str, Any],
        context: ExecutionContext,
        runtime: CapabilityRuntime,
    ) -> CapabilityResult:
        """为示例中的各个 Agent 返回离线 mock 数据。"""
        _ = context
        _ = runtime
        agent_id = spec.base.id

        if agent_id == "agent.idea_generator":
            topic = str(input.get("topic", "topic"))
            ideas = [
                f"{topic} blueprint",
                f"{topic} checklist",
                f"{topic} timeline",
            ]
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"ideas": ideas, "idea_count": len(ideas)},
            )

        if agent_id == "agent.idea_evaluator":
            ideas = list(input.get("ideas", []))
            best_idea = str(ideas[1]) if len(ideas) > 1 else "fallback idea"
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={
                    "best_idea": best_idea,
                    "score": 85,
                    "generated_count": input.get("generated_count"),
                },
            )

        if agent_id == "agent.report_writer":
            best_idea = str(input.get("best_idea", "n/a"))
            score = input.get("score")
            topic = str(input.get("topic", "n/a"))
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={
                    "report": (
                        f"Topic={topic}; selected={best_idea}; score={score}."
                    )
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
    """构建顺序工作流，演示 context/previous/step 三类映射。"""
    return WorkflowSpec(
        base=CapabilitySpec(
            id="workflow.sequential.demo",
            kind=CapabilityKind.WORKFLOW,
            name="Sequential Workflow Demo",
            description="Step + InputMapping demo",
        ),
        steps=[
            Step(
                id="generate",
                capability=CapabilityRef(id="agent.idea_generator"),
                input_mappings=[InputMapping(source="context.topic", target_field="topic")],
            ),
            Step(
                id="evaluate",
                capability=CapabilityRef(id="agent.idea_evaluator"),
                input_mappings=[
                    InputMapping(source="previous.ideas", target_field="ideas"),
                    InputMapping(
                        source="step.generate.idea_count",
                        target_field="generated_count",
                    ),
                ],
            ),
            Step(
                id="report",
                capability=CapabilityRef(id="agent.report_writer"),
                input_mappings=[
                    InputMapping(source="step.evaluate.best_idea", target_field="best_idea"),
                    InputMapping(source="previous.score", target_field="score"),
                    InputMapping(source="context.topic", target_field="topic"),
                ],
            ),
        ],
    )


async def main() -> None:
    """执行顺序工作流并打印每个步骤的输出。"""
    runtime = CapabilityRuntime(config=RuntimeConfig())
    runtime.set_adapter(CapabilityKind.AGENT, SequentialDemoAgentAdapter())
    runtime.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())

    runtime.register_many(
        [
            build_agent("agent.idea_generator", "Idea Generator"),
            build_agent("agent.idea_evaluator", "Idea Evaluator"),
            build_agent("agent.report_writer", "Report Writer"),
            build_workflow(),
        ]
    )

    missing = runtime.validate()
    if missing:
        raise RuntimeError(f"Missing capabilities: {missing}")

    result = await runtime.run(
        "workflow.sequential.demo",
        input={"topic": "release planning"},
    )
    if result.status != CapabilityStatus.SUCCESS:
        raise RuntimeError(f"Workflow failed: {result.error}")

    print("=== 02 workflow_sequential ===")
    print(f"workflow.status={result.status.value}")
    print("[generate]")
    print(pretty(result.output["generate"]))
    print("[evaluate]")
    print(pretty(result.output["evaluate"]))
    print("[report]")
    print(pretty(result.output["report"]))


if __name__ == "__main__":
    asyncio.run(main())
