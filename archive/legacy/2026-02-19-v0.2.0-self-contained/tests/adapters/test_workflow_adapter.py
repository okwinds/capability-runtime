from __future__ import annotations

import pytest

from capability_runtime.adapters.workflow_adapter import WorkflowAdapter
from capability_runtime.protocol.capability import CapabilityResult, CapabilityStatus
from capability_runtime.protocol.context import ExecutionContext
from capability_runtime.protocol.workflow import (
    ConditionalStep,
    InputMapping,
    LoopStep,
    ParallelStep,
    Step,
)
from capability_runtime.protocol.capability import CapabilityRef, CapabilityKind, CapabilitySpec
from capability_runtime.protocol.workflow import WorkflowSpec
from capability_runtime.runtime.guards import ExecutionGuards
from capability_runtime.runtime.loop import LoopController


class FakeRuntime:
    def __init__(self) -> None:
        class Cfg:
            max_loop_iterations = 100

        self.config = Cfg()
        self.loop_controller = LoopController(guards=ExecutionGuards(max_total_loop_iterations=1000))

    async def _execute(self, *, capability_id: str, input: dict, context: ExecutionContext) -> CapabilityResult:
        if capability_id == "fail":
            return CapabilityResult(status=CapabilityStatus.FAILED, error="boom")
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"id": capability_id, "input": input})


@pytest.mark.asyncio
async def test_workflow_step_and_default_output() -> None:
    rt = FakeRuntime()
    adapter = WorkflowAdapter()
    wf = WorkflowSpec(
        base=CapabilitySpec(id="wf", kind=CapabilityKind.WORKFLOW, name="WF"),
        steps=[
            Step(id="s1", capability=CapabilityRef(id="cap1"), input_mappings=[InputMapping(source="literal.x", target_field="x")]),
            Step(id="s2", capability=CapabilityRef(id="cap2")),
        ],
    )
    ctx = ExecutionContext(run_id="r", bag={"task": "t"})
    res = await adapter.execute(spec=wf, input={}, context=ctx, runtime=rt)
    assert res.status == CapabilityStatus.SUCCESS
    assert res.output["id"] == "cap2"
    assert "s1" in ctx.step_outputs and "s2" in ctx.step_outputs


@pytest.mark.asyncio
async def test_workflow_loop_step_uses_loop_controller() -> None:
    rt = FakeRuntime()
    adapter = WorkflowAdapter()
    wf = WorkflowSpec(
        base=CapabilitySpec(id="wf", kind=CapabilityKind.WORKFLOW, name="WF"),
        steps=[
            Step(id="plan", capability=CapabilityRef(id="cap-plan")),
            LoopStep(
                id="work",
                capability=CapabilityRef(id="cap-work"),
                iterate_over="context.items",
                item_input_mappings=[InputMapping(source="item", target_field="item")],
                collect_as="results",
            ),
        ],
    )
    ctx = ExecutionContext(run_id="r", bag={"items": [1, 2]})
    res = await adapter.execute(spec=wf, input={}, context=ctx, runtime=rt)
    assert res.status == CapabilityStatus.SUCCESS
    assert res.output["results"][0]["id"] == "cap-work"


@pytest.mark.asyncio
async def test_workflow_parallel_all_success_fails_if_any_fail() -> None:
    rt = FakeRuntime()
    adapter = WorkflowAdapter()
    wf = WorkflowSpec(
        base=CapabilitySpec(id="wf", kind=CapabilityKind.WORKFLOW, name="WF"),
        steps=[
            ParallelStep(id="p", branches=[Step(id="a", capability=CapabilityRef(id="ok")), Step(id="b", capability=CapabilityRef(id="fail"))]),
        ],
    )
    ctx = ExecutionContext(run_id="r")
    res = await adapter.execute(spec=wf, input={}, context=ctx, runtime=rt)
    assert res.status == CapabilityStatus.FAILED


@pytest.mark.asyncio
async def test_workflow_conditional_default_branch() -> None:
    rt = FakeRuntime()
    adapter = WorkflowAdapter()
    wf = WorkflowSpec(
        base=CapabilitySpec(id="wf", kind=CapabilityKind.WORKFLOW, name="WF"),
        steps=[
            ConditionalStep(
                id="c",
                condition_source="literal.nope",
                branches={"yes": Step(id="s-yes", capability=CapabilityRef(id="ok"))},
                default=Step(id="s-default", capability=CapabilityRef(id="ok2")),
            ),
        ],
    )
    ctx = ExecutionContext(run_id="r")
    res = await adapter.execute(spec=wf, input={}, context=ctx, runtime=rt)
    assert res.status == CapabilityStatus.SUCCESS
    assert res.output["id"] == "ok2"

