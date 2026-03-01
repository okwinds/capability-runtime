from __future__ import annotations

"""WorkflowSpec 单元测试。"""

from capability_runtime.protocol.capability import CapabilityKind, CapabilityRef, CapabilitySpec
from capability_runtime.protocol.workflow import (
    ConditionalStep,
    InputMapping,
    LoopStep,
    ParallelStep,
    Step,
    WorkflowSpec,
)


def test_step_construction():
    step = Step(
        id="s1",
        capability=CapabilityRef(id="MA-013A"),
        input_mappings=[InputMapping(source="context.故事梗概", target_field="故事梗概")],
        timeout_s=3.0,
    )
    assert step.id == "s1"
    assert step.capability.id == "MA-013A"
    assert len(step.input_mappings) == 1
    assert step.timeout_s == 3.0


def test_loop_step_construction():
    step = LoopStep(
        id="s2",
        capability=CapabilityRef(id="MA-013"),
        iterate_over="step.s1.角色列表",
        item_input_mappings=[InputMapping(source="item.定位", target_field="角色定位")],
        max_iterations=20,
        fail_strategy="skip",
        timeout_s=5.0,
    )
    assert step.iterate_over == "step.s1.角色列表"
    assert step.max_iterations == 20
    assert step.fail_strategy == "skip"
    assert step.timeout_s == 5.0


def test_parallel_step_construction():
    step = ParallelStep(
        id="p1",
        branches=[
            Step(id="b1", capability=CapabilityRef(id="MA-001")),
            Step(id="b2", capability=CapabilityRef(id="MA-002")),
            Step(id="b3", capability=CapabilityRef(id="MA-003")),
        ],
        join_strategy="all_success",
    )
    assert len(step.branches) == 3
    assert step.join_strategy == "all_success"


def test_conditional_step_construction():
    step = ConditionalStep(
        id="c1",
        condition_source="step.classify.category",
        branches={
            "romance": Step(id="br1", capability=CapabilityRef(id="MA-010")),
            "action": Step(id="br2", capability=CapabilityRef(id="MA-011")),
        },
        default=Step(id="default", capability=CapabilityRef(id="MA-012")),
    )
    assert len(step.branches) == 2
    assert step.default is not None


def test_workflow_spec_full():
    workflow = WorkflowSpec(
        base=CapabilitySpec(
            id="WF-001D",
            kind=CapabilityKind.WORKFLOW,
            name="人物塑造子流程",
        ),
        steps=[
            Step(id="s1", capability=CapabilityRef(id="MA-013A")),
            LoopStep(
                id="s2",
                capability=CapabilityRef(id="MA-013"),
                iterate_over="step.s1.角色列表",
                max_iterations=20,
            ),
            Step(id="s3", capability=CapabilityRef(id="MA-014")),
            LoopStep(
                id="s4",
                capability=CapabilityRef(id="MA-015"),
                iterate_over="step.s2",
                max_iterations=20,
            ),
        ],
        output_mappings=[
            InputMapping(source="step.s2", target_field="角色小传列表"),
            InputMapping(source="step.s3", target_field="关系图谱"),
        ],
    )
    assert len(workflow.steps) == 4
    assert len(workflow.output_mappings) == 2
