"""CapabilityRegistry 单元测试（方案2：仅 Agent/Workflow 原语）。"""
from __future__ import annotations

import pytest

from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.protocol.capability import (
    CapabilityKind,
    CapabilityRef,
    CapabilitySpec,
)
from agently_skills_runtime.protocol.workflow import (
    ConditionalStep,
    LoopStep,
    ParallelStep,
    Step,
    WorkflowSpec,
)
from agently_skills_runtime.registry import CapabilityRegistry


def _make_agent(id: str, collaborators=None, callable_workflows=None) -> AgentSpec:
    """构造最小 AgentSpec。"""

    return AgentSpec(
        base=CapabilitySpec(id=id, kind=CapabilityKind.AGENT, name=id),
        collaborators=collaborators or [],
        callable_workflows=callable_workflows or [],
    )


def _make_workflow(id: str, steps=None) -> WorkflowSpec:
    """构造最小 WorkflowSpec。"""

    return WorkflowSpec(
        base=CapabilitySpec(id=id, kind=CapabilityKind.WORKFLOW, name=id),
        steps=steps or [],
    )


class TestProtocolGuards:
    def test_capability_kind_rejects_skill_value(self) -> None:
        """方案2：Protocol 不再暴露 SKILL 原语，避免形成第二套 skills 体系。"""

        with pytest.raises(ValueError):
            CapabilityKind("skill")


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
        reg.register(_make_workflow("WF"))
        assert len(reg.list_all()) == 2

    def test_list_by_kind(self):
        reg = CapabilityRegistry()
        reg.register(_make_agent("A"))
        reg.register(_make_agent("B"))
        reg.register(_make_workflow("WF"))
        assert len(reg.list_by_kind(CapabilityKind.AGENT)) == 2
        assert len(reg.list_by_kind(CapabilityKind.WORKFLOW)) == 1

    def test_list_ids(self):
        reg = CapabilityRegistry()
        reg.register(_make_agent("A"))
        reg.register(_make_workflow("WF"))
        assert sorted(reg.list_ids()) == ["A", "WF"]

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

    def test_workflow_nested_branch_deps_are_collected_recursively(self) -> None:
        """
        回归护栏：依赖校验必须递归覆盖嵌套步骤结构。

        现象（旧行为）：
        - ParallelStep.branches/ConditionalStep.branches 若包含更深层的 Parallel/Conditional，
          validate_dependencies 可能误报“依赖齐全”，直到运行时才爆炸。
        """

        reg = CapabilityRegistry()
        wf = _make_workflow(
            "WF-NESTED",
            steps=[
                ParallelStep(
                    id="p1",
                    branches=[
                        ConditionalStep(
                            id="c1",
                            condition_source="context.x",
                            branches={"a": Step(id="leaf", capability=CapabilityRef(id="MISSING"))},
                        ),
                    ],  # type: ignore[arg-type]
                ),
            ],
        )
        reg.register(wf)

        assert reg.validate_dependencies() == ["MISSING"]

    def test_complex_mixed_dependencies(self) -> None:
        """同时覆盖 Agent 的 ref 依赖与 Workflow step 依赖收集。"""

        reg = CapabilityRegistry()
        reg.register(_make_agent("A", collaborators=[CapabilityRef(id="B")]))
        reg.register(
            _make_workflow(
                "WF",
                steps=[
                    Step(id="s1", capability=CapabilityRef(id="A")),
                    Step(id="s2", capability=CapabilityRef(id="C")),
                ],
            )
        )
        assert sorted(reg.validate_dependencies()) == ["B", "C"]
