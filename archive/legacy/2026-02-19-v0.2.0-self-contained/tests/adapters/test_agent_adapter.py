from __future__ import annotations

import pytest

from agently_skills_runtime.adapters.agent_adapter import AgentAdapter
from agently_skills_runtime.adapters.skill_adapter import SkillAdapter
from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.protocol.capability import CapabilityKind, CapabilityResult, CapabilitySpec, CapabilityStatus
from agently_skills_runtime.protocol.context import ExecutionContext
from agently_skills_runtime.protocol.skill import SkillSpec
from agently_skills_runtime.runtime.engine import CapabilityRuntime, RuntimeConfig


@pytest.mark.asyncio
async def test_agent_adapter_injects_skills_and_calls_runner() -> None:
    skill_adapter = SkillAdapter()

    captured = {}

    async def runner(*, spec: AgentSpec, input: dict, skills_text: str, context: ExecutionContext, runtime) -> CapabilityResult:  # type: ignore[no-untyped-def]
        captured["skills_text"] = skills_text
        captured["input"] = input
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"ok": True})

    agent_adapter = AgentAdapter(skill_adapter=skill_adapter, runner=runner)

    rt = CapabilityRuntime(config=RuntimeConfig(workspace_root="."), agent_adapter=agent_adapter, skill_adapter=skill_adapter)
    rt.register(SkillSpec(base=CapabilitySpec(id="skill-guide", kind=CapabilityKind.SKILL, name="Guide"), source="SKILL", source_type="inline"))
    rt.register(AgentSpec(base=CapabilitySpec(id="agent", kind=CapabilityKind.AGENT, name="A"), skills=["skill-guide"]))

    res = await rt.run("agent", input={"task": "x"})
    assert res.status == CapabilityStatus.SUCCESS
    assert "SKILL" in captured["skills_text"]
    assert captured["input"] == {"task": "x"}


@pytest.mark.asyncio
async def test_agent_adapter_injects_skills_declared_by_inject_to() -> None:
    skill_adapter = SkillAdapter()

    captured = {}

    async def runner(*, spec: AgentSpec, input: dict, skills_text: str, context: ExecutionContext, runtime) -> CapabilityResult:  # type: ignore[no-untyped-def]
        captured["skills_text"] = skills_text
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"ok": True})

    agent_adapter = AgentAdapter(skill_adapter=skill_adapter, runner=runner)

    rt = CapabilityRuntime(config=RuntimeConfig(workspace_root="."), agent_adapter=agent_adapter, skill_adapter=skill_adapter)
    rt.register(
        SkillSpec(
            base=CapabilitySpec(id="skill-explicit", kind=CapabilityKind.SKILL, name="Explicit"),
            source="EXPLICIT",
            source_type="inline",
        )
    )
    rt.register(
        SkillSpec(
            base=CapabilitySpec(id="skill-injected", kind=CapabilityKind.SKILL, name="Injected"),
            source="INJECTED",
            source_type="inline",
            inject_to=["agent"],
        )
    )
    rt.register(AgentSpec(base=CapabilitySpec(id="agent", kind=CapabilityKind.AGENT, name="A"), skills=["skill-explicit"]))

    res = await rt.run("agent", input={"task": "x"})
    assert res.status == CapabilityStatus.SUCCESS
    assert "EXPLICIT" in captured["skills_text"]
    assert "INJECTED" in captured["skills_text"]
    assert captured["skills_text"].find("EXPLICIT") < captured["skills_text"].find("INJECTED")


@pytest.mark.asyncio
async def test_agent_adapter_dedup_skills_between_explicit_and_inject_to() -> None:
    skill_adapter = SkillAdapter()

    captured = {"calls": 0}

    async def runner(*, spec: AgentSpec, input: dict, skills_text: str, context: ExecutionContext, runtime) -> CapabilityResult:  # type: ignore[no-untyped-def]
        captured["calls"] += 1
        captured["skills_text"] = skills_text
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"ok": True})

    agent_adapter = AgentAdapter(skill_adapter=skill_adapter, runner=runner)

    rt = CapabilityRuntime(config=RuntimeConfig(workspace_root="."), agent_adapter=agent_adapter, skill_adapter=skill_adapter)
    rt.register(
        SkillSpec(
            base=CapabilitySpec(id="skill-both", kind=CapabilityKind.SKILL, name="Both"),
            source="BOTH_SKILL",
            source_type="inline",
            inject_to=["agent"],
        )
    )
    rt.register(AgentSpec(base=CapabilitySpec(id="agent", kind=CapabilityKind.AGENT, name="A"), skills=["skill-both"]))

    res = await rt.run("agent", input={"task": "x"})
    assert res.status == CapabilityStatus.SUCCESS
    assert captured["calls"] == 1
    assert captured["skills_text"].count("BOTH_SKILL") == 1


@pytest.mark.asyncio
async def test_agent_adapter_missing_explicit_skill_returns_failed_and_does_not_call_runner() -> None:
    skill_adapter = SkillAdapter()

    captured = {"calls": 0}

    async def runner(*, spec: AgentSpec, input: dict, skills_text: str, context: ExecutionContext, runtime) -> CapabilityResult:  # type: ignore[no-untyped-def]
        captured["calls"] += 1
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"ok": True})

    agent_adapter = AgentAdapter(skill_adapter=skill_adapter, runner=runner)

    rt = CapabilityRuntime(config=RuntimeConfig(workspace_root="."), agent_adapter=agent_adapter, skill_adapter=skill_adapter)
    rt.register(AgentSpec(base=CapabilitySpec(id="agent", kind=CapabilityKind.AGENT, name="A"), skills=["skill-missing"]))

    res = await rt.run("agent", input={"task": "x"})
    assert res.status == CapabilityStatus.FAILED
    assert captured["calls"] == 0
