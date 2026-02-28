"""编辑整合 Agent 声明。"""
from __future__ import annotations

from capability_runtime import AgentIOSchema, AgentSpec, CapabilityKind, CapabilitySpec

spec = AgentSpec(
    base=CapabilitySpec(
        id="agent.content.editor",
        kind=CapabilityKind.AGENT,
        name="Editor",
        description="整合分段草稿，生成最终成稿。",
        tags=["content", "editing"],
    ),
    system_prompt="你是审稿编辑，负责整合结构并统一文风。",
    prompt_template=(
        "请整合内容草稿并输出最终稿。\n"
        "topic={topic}\n"
        "target_length={target_length}\n"
        "sections={sections}"
    ),
    output_schema=AgentIOSchema(
        fields={
            "title": "str",
            "final_draft": "str",
            "estimated_word_count": "int",
        },
        required=["title", "final_draft"],
    ),
)
