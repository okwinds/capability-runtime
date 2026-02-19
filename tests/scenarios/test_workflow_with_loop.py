from __future__ import annotations

import pytest

from agently_skills_runtime.adapters.agent_adapter import AgentAdapter
from agently_skills_runtime.adapters.skill_adapter import SkillAdapter
from agently_skills_runtime.adapters.workflow_adapter import WorkflowAdapter
from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.protocol.capability import CapabilityKind, CapabilityResult, CapabilitySpec, CapabilityStatus
from agently_skills_runtime.protocol.context import ExecutionContext
from agently_skills_runtime.protocol.skill import SkillSpec
from agently_skills_runtime.protocol.workflow import InputMapping, LoopStep, Step, WorkflowSpec
from agently_skills_runtime.runtime.engine import CapabilityRuntime, RuntimeConfig
from agently_skills_runtime.protocol.capability import CapabilityRef


@pytest.mark.asyncio
async def test_workflow_with_two_agents_and_loop_mock_runner() -> None:
    skill_adapter = SkillAdapter()

    async def runner(*, spec: AgentSpec, input: dict, skills_text: str, context: ExecutionContext, runtime) -> CapabilityResult:  # type: ignore[no-untyped-def]
        if spec.base.id == "agent-planner":
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"items": [{"name": "a"}, {"name": "b"}]})
        if spec.base.id == "agent-worker":
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"done": input.get("item")})
        return CapabilityResult(status=CapabilityStatus.FAILED, error="unknown agent")

    agent_adapter = AgentAdapter(skill_adapter=skill_adapter, runner=runner)
    workflow_adapter = WorkflowAdapter()

    rt = CapabilityRuntime(
        config=RuntimeConfig(workspace_root="."),
        skill_adapter=skill_adapter,
        agent_adapter=agent_adapter,
        workflow_adapter=workflow_adapter,
    )

    rt.register(SkillSpec(base=CapabilitySpec(id="skill-guide", kind=CapabilityKind.SKILL, name="Guide"), source="GUIDE", source_type="inline"))
    rt.register(AgentSpec(base=CapabilitySpec(id="agent-planner", kind=CapabilityKind.AGENT, name="Planner"), skills=["skill-guide"]))
    rt.register(
        AgentSpec(
            base=CapabilitySpec(id="agent-worker", kind=CapabilityKind.AGENT, name="Worker"),
            skills=["skill-guide"],
            loop_compatible=True,
        )
    )
    rt.register(
        WorkflowSpec(
            base=CapabilitySpec(id="wf-main", kind=CapabilityKind.WORKFLOW, name="Main"),
            steps=[
                Step(
                    id="plan",
                    capability=CapabilityRef(id="agent-planner"),
                    input_mappings=[InputMapping(source="context.task", target_field="task")],
                ),
                LoopStep(
                    id="work",
                    capability=CapabilityRef(id="agent-worker"),
                    iterate_over="step.plan.items",
                    item_input_mappings=[InputMapping(source="item", target_field="item")],
                    max_iterations=50,
                    collect_as="results",
                ),
            ],
        )
    )

    rt.validate()
    res = await rt.run("wf-main", context_bag={"task": "do"})
    assert res.status == CapabilityStatus.SUCCESS
    assert res.output["results"][0]["done"]["name"] == "a"

