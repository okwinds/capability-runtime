from __future__ import annotations

from capability_runtime.protocol.capability import CapabilityKind, CapabilityRef, CapabilitySpec
from capability_runtime.protocol.workflow import (
    ConditionalStep,
    InputMapping,
    LoopStep,
    ParallelStep,
    Step,
    WorkflowSpec,
)


def test_workflow_spec_constructible() -> None:
    base = CapabilitySpec(id="wf", kind=CapabilityKind.WORKFLOW, name="WF")
    wf = WorkflowSpec(base=base, steps=[])
    assert wf.base.id == "wf"
    assert wf.steps == []


def test_workflow_steps_constructible() -> None:
    ref = CapabilityRef(id="cap-x")
    step = Step(id="s1", capability=ref, input_mappings=[InputMapping(source="literal.x", target_field="x")])
    loop = LoopStep(id="l1", capability=ref, iterate_over="context.items")
    par = ParallelStep(id="p1", branches=[step, loop], join_strategy="all_success")
    cond = ConditionalStep(id="c1", condition_source="context.flag", branches={"y": step}, default=loop)
    assert step.id == "s1"
    assert loop.iterate_over == "context.items"
    assert par.join_strategy == "all_success"
    assert cond.condition_source == "context.flag"

