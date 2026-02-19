from __future__ import annotations

"""SkillSpec 单元测试。"""

from agently_skills_runtime.protocol.capability import CapabilityKind, CapabilityRef, CapabilitySpec
from agently_skills_runtime.protocol.skill import SkillDispatchRule, SkillSpec


def test_skill_spec_file():
    spec = SkillSpec(
        base=CapabilitySpec(id="story-tpl", kind=CapabilityKind.SKILL, name="故事模板"),
        source="skills/story-template/SKILL.md",
        source_type="file",
    )
    assert spec.base.id == "story-tpl"
    assert spec.source_type == "file"
    assert spec.dispatch_rules == []
    assert spec.inject_to == []


def test_skill_spec_inline():
    spec = SkillSpec(
        base=CapabilitySpec(id="inline-s", kind=CapabilityKind.SKILL, name="内联"),
        source="这是 Skill 内容文本",
        source_type="inline",
    )
    assert spec.source_type == "inline"
    assert "Skill 内容" in spec.source


def test_skill_dispatch_rule():
    rule = SkillDispatchRule(
        condition="low_score",
        target=CapabilityRef(id="MA-007"),
        priority=10,
    )
    assert rule.condition == "low_score"
    assert rule.target.id == "MA-007"
    assert rule.priority == 10


def test_skill_inject_to():
    spec = SkillSpec(
        base=CapabilitySpec(id="char-tpl", kind=CapabilityKind.SKILL, name="角色模板"),
        source="inline content",
        source_type="inline",
        inject_to=["MA-013", "MA-014"],
    )
    assert "MA-013" in spec.inject_to
    assert "MA-014" in spec.inject_to
