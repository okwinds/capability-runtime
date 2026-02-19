from __future__ import annotations

import pytest

from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.protocol.capability import (
    CapabilityKind,
    CapabilityResult,
    CapabilitySpec,
    CapabilityStatus,
)
from agently_skills_runtime.protocol.context import ExecutionContext
from agently_skills_runtime.protocol.skill import SkillSpec
from agently_skills_runtime.protocol.workflow import WorkflowSpec
from agently_skills_runtime.runtime.engine import CapabilityRuntime, RuntimeConfig


class FakeSkillAdapter:
    def __init__(self) -> None:
        self.called = 0

    async def execute(self, *, spec: SkillSpec, input: dict, context: ExecutionContext, runtime: CapabilityRuntime) -> CapabilityResult:
        self.called += 1
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"kind": "skill", "id": spec.base.id})


class FakeAgentAdapter:
    def __init__(self) -> None:
        self.called = 0

    async def execute(self, *, spec: AgentSpec, input: dict, context: ExecutionContext, runtime: CapabilityRuntime) -> CapabilityResult:
        self.called += 1
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"kind": "agent", "id": spec.base.id})


class FakeWorkflowAdapter:
    def __init__(self) -> None:
        self.called = 0

    async def execute(self, *, spec: WorkflowSpec, input: dict, context: ExecutionContext, runtime: CapabilityRuntime) -> CapabilityResult:
        self.called += 1
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"kind": "workflow", "id": spec.base.id})


@pytest.mark.asyncio
async def test_engine_dispatches_by_kind() -> None:
    s_ad = FakeSkillAdapter()
    a_ad = FakeAgentAdapter()
    w_ad = FakeWorkflowAdapter()
    rt = CapabilityRuntime(config=RuntimeConfig(), skill_adapter=s_ad, agent_adapter=a_ad, workflow_adapter=w_ad)

    rt.register(SkillSpec(base=CapabilitySpec(id="s", kind=CapabilityKind.SKILL, name="S"), source="inline"))
    rt.register(AgentSpec(base=CapabilitySpec(id="a", kind=CapabilityKind.AGENT, name="A")))
    rt.register(WorkflowSpec(base=CapabilitySpec(id="w", kind=CapabilityKind.WORKFLOW, name="W")))

    rt.validate()

    res_s = await rt.run("s")
    res_a = await rt.run("a")
    res_w = await rt.run("w")

    assert res_s.output["kind"] == "skill"
    assert res_a.output["kind"] == "agent"
    assert res_w.output["kind"] == "workflow"
    assert s_ad.called == 1
    assert a_ad.called == 1
    assert w_ad.called == 1


@pytest.mark.asyncio
async def test_engine_missing_capability_returns_failed() -> None:
    rt = CapabilityRuntime(config=RuntimeConfig())
    res = await rt.run("missing")
    assert res.status == CapabilityStatus.FAILED

