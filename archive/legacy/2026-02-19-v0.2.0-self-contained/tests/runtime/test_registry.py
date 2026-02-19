from __future__ import annotations

from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.protocol.capability import CapabilityKind, CapabilityRef, CapabilitySpec
from agently_skills_runtime.protocol.skill import SkillDispatchRule, SkillSpec
from agently_skills_runtime.protocol.workflow import (
    ConditionalStep,
    LoopStep,
    ParallelStep,
    Step,
    WorkflowSpec,
)
from agently_skills_runtime.runtime.registry import CapabilityRegistry


def test_registry_register_get_list_by_kind() -> None:
    reg = CapabilityRegistry()
    skill = SkillSpec(base=CapabilitySpec(id="s", kind=CapabilityKind.SKILL, name="S"), source="inline")
    agent = AgentSpec(base=CapabilitySpec(id="a", kind=CapabilityKind.AGENT, name="A"))
    reg.register(skill)
    reg.register(agent)
    assert reg.get("s") is skill
    assert reg.get_or_raise("a") is agent
    assert [x.base.id for x in reg.list_by_kind(CapabilityKind.SKILL)] == ["s"]


def test_validate_dependencies_agent_missing_skill() -> None:
    reg = CapabilityRegistry()
    agent = AgentSpec(base=CapabilitySpec(id="a", kind=CapabilityKind.AGENT, name="A"), skills=["missing"])
    reg.register(agent)
    errs = reg.validate_dependencies()
    assert any("missing dependency" in e and "missing" in e for e in errs)


def test_validate_dependencies_workflow_nested_missing_refs() -> None:
    reg = CapabilityRegistry()
    wf = WorkflowSpec(
        base=CapabilitySpec(id="wf", kind=CapabilityKind.WORKFLOW, name="WF"),
        steps=[
            ParallelStep(
                id="p",
                branches=[Step(id="s1", capability=CapabilityRef(id="missing-cap"))],
            ),
            ConditionalStep(
                id="c",
                condition_source="literal.x",
                branches={"x": LoopStep(id="l", capability=CapabilityRef(id="missing-cap-2"), iterate_over="literal.[]")},
            ),
        ],
    )
    reg.register(wf)
    errs = reg.validate_dependencies()
    assert any("missing-cap" in e for e in errs)
    assert any("missing-cap-2" in e for e in errs)


def test_validate_dependencies_skill_dispatch_rule_target() -> None:
    reg = CapabilityRegistry()
    skill = SkillSpec(
        base=CapabilitySpec(id="s", kind=CapabilityKind.SKILL, name="S"),
        source="inline",
        dispatch_rules=[SkillDispatchRule(condition="context.x", target=CapabilityRef(id="missing-target"))],
    )
    reg.register(skill)
    errs = reg.validate_dependencies()
    assert any("missing-target" in e for e in errs)
