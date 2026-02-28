"""示例 09：完整内容创作场景（Pipeline + Fan-out）离线 mock。"""
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


class FullScenarioMockAdapter:
    """按 agent_id 返回可解释的 mock 数据。"""

    async def execute(
        self,
        *,
        spec: AgentSpec,
        input: dict[str, Any],
        context: ExecutionContext,
        runtime: CapabilityRuntime,
    ) -> CapabilityResult:
        _ = context
        _ = runtime
        aid = spec.base.id

        if aid == "agent.topic_analyst":
            topic = str(input.get("raw_idea", "untitled concept")).strip() or "untitled concept"
            angles = [f"问题定义：{topic}", f"方案拆解：{topic}", f"落地路径：{topic}"]
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"topic": topic, "angles": angles})

        if aid == "agent.angle_writer":
            topic = str(input.get("topic", "unknown"))
            angle = str(input.get("angle", "unknown"))
            section = f"围绕《{topic}》展开 {angle}，给出关键观点与行动建议。"
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"angle": angle, "section": section})

        if aid == "agent.editor":
            topic = str(input.get("topic", "unknown"))
            sections = input.get("sections", [])
            lines = []
            if isinstance(sections, list):
                for idx, item in enumerate(sections, start=1):
                    text = item.get("section", "") if isinstance(item, dict) else str(item)
                    lines.append(f"{idx}. {text}")
            draft = f"主题：{topic}\n" + "\n".join(lines)
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"final_draft": draft, "word_count": max(1200, 800 + len(draft) // 2)},
            )

        if aid == "agent.quality_checker":
            draft = str(input.get("final_draft", ""))
            issues = [] if "建议" in draft else ["缺少明确行动建议"]
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"quality_score": 88 if len(draft) > 120 else 72, "issues": issues},
            )

        return CapabilityResult(status=CapabilityStatus.FAILED, error=f"Unsupported agent id: {aid}")


def build_workflow() -> WorkflowSpec:
    """声明完整工作流：分析 -> 循环扩写 -> 编辑 -> 质检。"""
    return WorkflowSpec(
        base=CapabilitySpec(
            id="workflow.content_creation",
            kind=CapabilityKind.WORKFLOW,
            name="Content Creation Workflow",
            description="Pipeline + Fan-out full scenario",
        ),
        steps=[
            Step(
                id="topic_analysis",
                capability=CapabilityRef(id="agent.topic_analyst"),
                input_mappings=[InputMapping(source="context.raw_idea", target_field="raw_idea")],
            ),
            LoopStep(
                id="angle_development",
                capability=CapabilityRef(id="agent.angle_writer"),
                iterate_over="step.topic_analysis.angles",
                item_input_mappings=[
                    InputMapping(source="item", target_field="angle"),
                    InputMapping(source="step.topic_analysis.topic", target_field="topic"),
                ],
                max_iterations=10,
            ),
            Step(
                id="editing",
                capability=CapabilityRef(id="agent.editor"),
                input_mappings=[
                    InputMapping(source="step.topic_analysis.topic", target_field="topic"),
                    InputMapping(source="step.angle_development", target_field="sections"),
                ],
            ),
            Step(
                id="quality_check",
                capability=CapabilityRef(id="agent.quality_checker"),
                input_mappings=[InputMapping(source="step.editing.final_draft", target_field="final_draft")],
            ),
        ],
        output_mappings=[
            InputMapping(source="step.topic_analysis.topic", target_field="topic"),
            InputMapping(source="step.topic_analysis.angles", target_field="angles"),
            InputMapping(source="step.angle_development", target_field="sections"),
            InputMapping(source="step.editing.final_draft", target_field="final_draft"),
            InputMapping(source="step.editing.word_count", target_field="word_count"),
            InputMapping(source="step.quality_check.quality_score", target_field="quality_score"),
            InputMapping(source="step.quality_check.issues", target_field="issues"),
        ],
    )


async def main() -> None:
    """注册 4 个 Agent + 1 个 Workflow，并执行离线场景。"""
    runtime = CapabilityRuntime(config=RuntimeConfig())
    runtime.set_adapter(CapabilityKind.AGENT, FullScenarioMockAdapter())
    runtime.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    runtime.register_many(
        [
            AgentSpec(base=CapabilitySpec(id="agent.topic_analyst", kind=CapabilityKind.AGENT, name="Topic Analyst")),
            AgentSpec(base=CapabilitySpec(id="agent.angle_writer", kind=CapabilityKind.AGENT, name="Angle Writer")),
            AgentSpec(base=CapabilitySpec(id="agent.editor", kind=CapabilityKind.AGENT, name="Editor")),
            AgentSpec(base=CapabilitySpec(id="agent.quality_checker", kind=CapabilityKind.AGENT, name="Quality Checker")),
            build_workflow(),
        ]
    )

    result = await runtime.run(
        "workflow.content_creation",
        input={"raw_idea": "如何把能力运行时落地到多团队协作流程"},
    )
    print("=== 09 full_scenario_mock ===")
    print(f"workflow.status={result.status.value}")
    print(json.dumps(result.output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
