"""场景测试：Workflow 嵌套 Workflow。"""
from __future__ import annotations

import pytest

from agently_skills_runtime.adapters.workflow_adapter import WorkflowAdapter
from agently_skills_runtime.protocol.capability import (
    CapabilityKind,
    CapabilityRef,
    CapabilityResult,
    CapabilitySpec,
    CapabilityStatus,
)
from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.protocol.workflow import Step, WorkflowSpec
from agently_skills_runtime.runtime.engine import CapabilityRuntime, RuntimeConfig


class SimpleAdapter:
    async def execute(self, *, spec, input, context, runtime):
        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output={"from": spec.base.id, "depth": context.depth},
        )


@pytest.mark.asyncio
async def test_workflow_calls_workflow():
    """WF-outer → WF-inner → Agent A"""
    inner = WorkflowSpec(
        base=CapabilitySpec(id="WF-inner", kind=CapabilityKind.WORKFLOW, name="inner"),
        steps=[Step(id="s1", capability=CapabilityRef(id="A"))],
    )
    outer = WorkflowSpec(
        base=CapabilitySpec(id="WF-outer", kind=CapabilityKind.WORKFLOW, name="outer"),
        steps=[Step(id="s1", capability=CapabilityRef(id="WF-inner"))],
    )
    agent = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
    )

    rt = CapabilityRuntime(config=RuntimeConfig(max_depth=10))
    rt.set_adapter(CapabilityKind.AGENT, SimpleAdapter())
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    rt.register_many([agent, inner, outer])

    result = await rt.run("WF-outer")
    assert result.status == CapabilityStatus.SUCCESS


@pytest.mark.asyncio
async def test_deep_nesting_hits_limit():
    """深层嵌套超过 max_depth。"""
    specs = []
    for i in range(5):
        next_id = f"WF-{i+1}" if i < 4 else "A"
        wf = WorkflowSpec(
            base=CapabilitySpec(
                id=f"WF-{i}", kind=CapabilityKind.WORKFLOW, name=f"wf-{i}"
            ),
            steps=[Step(id="s1", capability=CapabilityRef(id=next_id))],
        )
        specs.append(wf)
    specs.append(
        AgentSpec(
            base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
        )
    )

    rt = CapabilityRuntime(config=RuntimeConfig(max_depth=3))
    rt.set_adapter(CapabilityKind.AGENT, SimpleAdapter())
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    rt.register_many(specs)

    result = await rt.run("WF-0")
    assert result.status == CapabilityStatus.FAILED
    assert "recursion" in (result.error or "").lower() or "depth" in (result.error or "").lower()
