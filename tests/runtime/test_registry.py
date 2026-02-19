"""CapabilityRegistry 单元测试。"""
from __future__ import annotations

import pytest

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


def _make_agent(id: str, skills=None, collaborators=None, callable_workflows=None) -> AgentSpec:
    return AgentSpec(
        base=CapabilitySpec(id=id, kind=CapabilityKind.AGENT, name=id),
        skills=skills or [],
        collaborators=collaborators or [],
        callable_workflows=callable_workflows or [],
    )


def _make_skill(id: str, inject_to=None, dispatch_rules=None) -> SkillSpec:
    return SkillSpec(
        base=CapabilitySpec(id=id, kind=CapabilityKind.SKILL, name=id),
        source="inline content",
        source_type="inline",
        inject_to=inject_to or [],
        dispatch_rules=dispatch_rules or [],
    )


def _make_workflow(id: str, steps=None) -> WorkflowSpec:
    return WorkflowSpec(
        base=CapabilitySpec(id=id, kind=CapabilityKind.WORKFLOW, name=id),
        steps=steps or [],
    )


class TestRegistryCRUD:
    def test_register_and_get(self):
        reg = CapabilityRegistry()
        agent = _make_agent("MA-013")
        reg.register(agent)
        assert reg.get("MA-013") is agent

    def test_get_nonexistent_returns_none(self):
        reg = CapabilityRegistry()
        assert reg.get("nonexistent") is None

    def test_get_or_raise_nonexistent(self):
        reg = CapabilityRegistry()
        with pytest.raises(KeyError, match="nonexistent"):
            reg.get_or_raise("nonexistent")

    def test_register_overwrites(self):
        reg = CapabilityRegistry()
        a1 = _make_agent("X")
        a2 = _make_agent("X")
        reg.register(a1)
        reg.register(a2)
        assert reg.get("X") is a2

    def test_list_all(self):
        reg = CapabilityRegistry()
        reg.register(_make_agent("A"))
        reg.register(_make_skill("B"))
        assert len(reg.list_all()) == 2

    def test_list_by_kind(self):
        reg = CapabilityRegistry()
        reg.register(_make_agent("A"))
        reg.register(_make_agent("B"))
        reg.register(_make_skill("C"))
        assert len(reg.list_by_kind(CapabilityKind.AGENT)) == 2
        assert len(reg.list_by_kind(CapabilityKind.SKILL)) == 1
        assert len(reg.list_by_kind(CapabilityKind.WORKFLOW)) == 0

    def test_list_ids(self):
        reg = CapabilityRegistry()
        reg.register(_make_agent("A"))
        reg.register(_make_skill("B"))
        assert sorted(reg.list_ids()) == ["A", "B"]

    def test_has(self):
        reg = CapabilityRegistry()
        reg.register(_make_agent("A"))
        assert reg.has("A")
        assert not reg.has("B")

    def test_unregister(self):
        reg = CapabilityRegistry()
        reg.register(_make_agent("A"))
        assert reg.unregister("A") is True
        assert reg.has("A") is False
        assert reg.unregister("A") is False


class TestValidateDependencies:
    def test_no_dependencies_all_ok(self):
        reg = CapabilityRegistry()
        reg.register(_make_agent("A"))
        assert reg.validate_dependencies() == []

    def test_agent_missing_skill(self):
        reg = CapabilityRegistry()
        reg.register(_make_agent("A", skills=["missing-skill"]))
        assert reg.validate_dependencies() == ["missing-skill"]

    def test_agent_skill_present(self):
        reg = CapabilityRegistry()
        reg.register(_make_skill("s1"))
        reg.register(_make_agent("A", skills=["s1"]))
        assert reg.validate_dependencies() == []

    def test_agent_missing_collaborator(self):
        reg = CapabilityRegistry()
        reg.register(_make_agent("A", collaborators=[CapabilityRef(id="B")]))
        assert reg.validate_dependencies() == ["B"]

    def test_agent_missing_callable_workflow(self):
        reg = CapabilityRegistry()
        reg.register(_make_agent("A", callable_workflows=[CapabilityRef(id="WF-X")]))
        assert reg.validate_dependencies() == ["WF-X"]

    def test_workflow_missing_step_capability(self):
        reg = CapabilityRegistry()
        wf = _make_workflow(
            "WF-1",
            steps=[
                Step(id="s1", capability=CapabilityRef(id="MA-001")),
                LoopStep(id="s2", capability=CapabilityRef(id="MA-002"), iterate_over="x"),
            ],
        )
        reg.register(wf)
        assert sorted(reg.validate_dependencies()) == ["MA-001", "MA-002"]

    def test_workflow_parallel_step_deps(self):
        reg = CapabilityRegistry()
        wf = _make_workflow(
            "WF-1",
            steps=[
                ParallelStep(
                    id="p1",
                    branches=[
                        Step(id="b1", capability=CapabilityRef(id="A")),
                        Step(id="b2", capability=CapabilityRef(id="B")),
                    ],
                ),
            ],
        )
        reg.register(wf)
        assert sorted(reg.validate_dependencies()) == ["A", "B"]

    def test_workflow_conditional_step_deps(self):
        reg = CapabilityRegistry()
        wf = _make_workflow(
            "WF-1",
            steps=[
                ConditionalStep(
                    id="c1",
                    condition_source="x",
                    branches={"a": Step(id="b1", capability=CapabilityRef(id="A"))},
                    default=Step(id="d1", capability=CapabilityRef(id="D")),
                ),
            ],
        )
        reg.register(wf)
        assert sorted(reg.validate_dependencies()) == ["A", "D"]

    def test_skill_dispatch_rule_missing_target(self):
        reg = CapabilityRegistry()
        reg.register(
            _make_skill(
                "s1",
                dispatch_rules=[
                    SkillDispatchRule(condition="x", target=CapabilityRef(id="MISSING")),
                ],
            )
        )
        assert reg.validate_dependencies() == ["MISSING"]

    def test_complex_mixed_dependencies(self):
        reg = CapabilityRegistry()
        reg.register(_make_skill("sk1"))
        reg.register(_make_agent("A", skills=["sk1", "sk2"]))
        reg.register(
            _make_workflow(
                "WF",
                steps=[
                    Step(id="s1", capability=CapabilityRef(id="A")),
                    Step(id="s2", capability=CapabilityRef(id="B")),
                ],
            )
        )
        assert sorted(reg.validate_dependencies()) == ["B", "sk2"]


class TestFindSkillsInjectingTo:
    def test_find_matching(self):
        reg = CapabilityRegistry()
        s1 = _make_skill("s1", inject_to=["MA-013", "MA-014"])
        s2 = _make_skill("s2", inject_to=["MA-013"])
        s3 = _make_skill("s3", inject_to=["MA-015"])
        reg.register(s1)
        reg.register(s2)
        reg.register(s3)
        result = reg.find_skills_injecting_to("MA-013")
        assert len(result) == 2
        ids = [s.base.id for s in result]
        assert "s1" in ids
        assert "s2" in ids

    def test_find_no_match(self):
        reg = CapabilityRegistry()
        reg.register(_make_skill("s1", inject_to=["MA-015"]))
        assert reg.find_skills_injecting_to("MA-013") == []

