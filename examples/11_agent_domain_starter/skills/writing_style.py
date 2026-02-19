"""写作风格 Skill 声明。"""
from __future__ import annotations

from agently_skills_runtime import CapabilityKind, CapabilitySpec, SkillSpec

spec = SkillSpec(
    base=CapabilitySpec(
        id="skill.content.writing_style",
        kind=CapabilityKind.SKILL,
        name="Writing Style Guide",
        description="内容写作风格约束，自动注入 writer。",
        tags=["content", "style"],
    ),
    source_type="inline",
    source=(
        "写作规则：\n"
        "1) 每段先给结论，再给理由；\n"
        "2) 避免空泛表述，优先给可执行建议；\n"
        "3) 用词克制，避免夸张营销语气。"
    ),
    inject_to=["agent.content.angle_writer"],
)
