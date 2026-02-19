"""角度扩写 Agent 声明。"""
from __future__ import annotations

from agently_skills_runtime import AgentIOSchema, AgentSpec, CapabilityKind, CapabilitySpec

spec = AgentSpec(
    base=CapabilitySpec(
        id="agent.content.angle_writer",
        kind=CapabilityKind.AGENT,
        name="Angle Writer",
        description="针对单个角度生成可合并的小节草稿。",
        tags=["content", "draft"],
    ),
    system_prompt="你是结构化写作助手，优先输出观点和执行建议。",
    prompt_template=(
        "请围绕以下信息写一个小节草稿。\n"
        "topic={topic}\n"
        "angle={angle}\n"
        "audience={audience}"
    ),
    output_schema=AgentIOSchema(
        fields={
            "angle": "str",
            "section_title": "str",
            "section_body": "str",
        },
        required=["angle", "section_title", "section_body"],
    ),
    loop_compatible=True,
)
