"""Runtime（统一入口）单元测试（mock 模式为主）。"""
from __future__ import annotations

import pytest

from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.protocol.capability import (
    CapabilityKind,
    CapabilityRef,
    CapabilitySpec,
    CapabilityStatus,
)
from agently_skills_runtime.protocol.workflow import Step, WorkflowSpec
from agently_skills_runtime.runtime import Runtime
from agently_skills_runtime.config import RuntimeConfig


def _make_agent(id: str) -> AgentSpec:
    return AgentSpec(
        base=CapabilitySpec(id=id, kind=CapabilityKind.AGENT, name=id),
    )


@pytest.mark.asyncio
async def test_run_agent_mock_default_handler():
    rt = Runtime(RuntimeConfig(mode="mock"))
    rt.register(_make_agent("A"))
    result = await rt.run("A", input={"x": 1})
    assert result.status == CapabilityStatus.SUCCESS
    assert isinstance(result.output, dict)
    assert result.output.get("mock") is True
    assert result.output.get("id") == "A"


@pytest.mark.asyncio
async def test_run_not_found():
    rt = Runtime(RuntimeConfig(mode="mock"))
    result = await rt.run("nonexistent")
    assert result.status == CapabilityStatus.FAILED
    assert "not found" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_run_workflow_mock_handler_executes_steps():
    def handler(spec: AgentSpec, input_dict):
        return {**dict(input_dict), "__agent__": spec.base.id}

    rt = Runtime(RuntimeConfig(mode="mock", mock_handler=handler))
    rt.register_many([_make_agent("A"), _make_agent("B")])
    rt.register(
        WorkflowSpec(
            base=CapabilitySpec(id="WF-1", kind=CapabilityKind.WORKFLOW, name="wf"),
            steps=[
                Step(id="s1", capability=CapabilityRef(id="A")),
                Step(id="s2", capability=CapabilityRef(id="B")),
            ],
        )
    )

    result = await rt.run("WF-1", input={"x": 1})
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output["s1"]["__agent__"] == "A"
    assert result.output["s2"]["__agent__"] == "B"


@pytest.mark.asyncio
async def test_register_many():
    rt = Runtime(RuntimeConfig(mode="mock"))
    rt.register_many([_make_agent("A"), _make_agent("B")])
    assert rt.validate() == []


@pytest.mark.asyncio
async def test_validate():
    rt = Runtime(RuntimeConfig(mode="mock"))
    rt.register(
        AgentSpec(
            base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
            collaborators=[CapabilityRef(id="missing-collaborator")],
        )
    )
    missing = rt.validate()
    assert "missing-collaborator" in missing


@pytest.mark.asyncio
async def test_run_agent_mock_handler_exception_surfaces_as_failed():
    def handler(_spec: AgentSpec, _input):  # pragma: no cover
        raise RuntimeError("boom")

    rt = Runtime(RuntimeConfig(mode="mock", mock_handler=handler))
    rt.register(_make_agent("A"))
    result = await rt.run("A")
    assert result.status == CapabilityStatus.FAILED
    assert "boom" in (result.error or "")

