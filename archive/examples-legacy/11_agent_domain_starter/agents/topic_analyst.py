"""选题分析 Agent 声明。"""
from __future__ import annotations

from agently_skills_runtime import AgentIOSchema, AgentSpec, CapabilityKind, CapabilitySpec

spec = AgentSpec(
    base=CapabilitySpec(
        id="agent.content.topic_analyst",
        kind=CapabilityKind.AGENT,
        name="Topic Analyst",
        description="把原始创意提炼成可执行内容选题和角度列表。",
        tags=["content", "analysis"],
    ),
    system_prompt="你是资深内容策略师，输出必须结构化、可执行。",
    prompt_template=(
        "请分析以下创作想法并输出结构化结果。\n"
        "raw_idea={raw_idea}\n"
        "audience={audience}"
    ),
    output_schema=AgentIOSchema(
        fields={
            "topic": "str",
            "angles": "list[str]",
            "reasoning": "str",
        },
        required=["topic", "angles"],
    ),
)
