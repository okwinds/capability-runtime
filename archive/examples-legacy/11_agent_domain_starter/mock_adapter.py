"""业务域离线 mock adapter。"""
from __future__ import annotations

from typing import Any

from agently_skills_runtime import (
    AgentSpec,
    CapabilityResult,
    CapabilityRuntime,
    CapabilityStatus,
    ExecutionContext,
)


class MockAgentAdapter:
    """按 agent_id 返回不同结构化数据，用于离线联调。"""

    async def execute(
        self,
        *,
        spec: AgentSpec,
        input: dict[str, Any],
        context: ExecutionContext,
        runtime: CapabilityRuntime,
    ) -> CapabilityResult:
        """执行 mock 推理，模拟三个业务 Agent 的不同输出。"""
        _ = context
        _ = runtime
        agent_id = spec.base.id

        if agent_id == "agent.content.topic_analyst":
            raw_idea = str(input.get("raw_idea", "未命名想法")).strip() or "未命名想法"
            audience = str(input.get("audience", "通用读者"))
            topic = f"{raw_idea}：面向{audience}的落地实践"
            angles = [
                "问题与机会识别",
                "方案设计与能力拆解",
                "实施路径与风险控制",
            ]
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={
                    "topic": topic,
                    "angles": angles,
                    "reasoning": "基于受众价值、可执行性与差异化进行筛选。",
                },
            )

        if agent_id == "agent.content.angle_writer":
            topic = str(input.get("topic", "未知主题"))
            angle = str(input.get("angle", "未知角度"))
            body = (
                f"围绕《{topic}》的“{angle}”，建议先定义目标、再拆分动作，"
                "最后给出可验证指标。"
            )
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={
                    "angle": angle,
                    "section_title": angle,
                    "section_body": body,
                },
            )

        if agent_id == "agent.content.editor":
            topic = str(input.get("topic", "未知主题"))
            target_length = int(input.get("target_length", 1200) or 1200)
            sections = input.get("sections", [])
            lines: list[str] = []
            if isinstance(sections, list):
                for idx, section in enumerate(sections, start=1):
                    if isinstance(section, dict):
                        title = str(section.get("section_title", f"小节{idx}"))
                        body = str(section.get("section_body", ""))
                    else:
                        title = f"小节{idx}"
                        body = str(section)
                    lines.append(f"{idx}. {title}\n{body}")
            final_draft = f"主题：{topic}\n\n" + "\n\n".join(lines)
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={
                    "title": topic,
                    "final_draft": final_draft,
                    "estimated_word_count": max(target_length, len(final_draft)),
                },
            )

        return CapabilityResult(
            status=CapabilityStatus.FAILED,
            error=f"Unsupported agent id: {agent_id}",
        )
