"""内容创作 Workflow 声明。"""
from __future__ import annotations

from agently_skills_runtime import (
    CapabilityKind,
    CapabilityRef,
    CapabilitySpec,
    InputMapping,
    LoopStep,
    Step,
    WorkflowSpec,
)

spec = WorkflowSpec(
    base=CapabilitySpec(
        id="workflow.content.creation",
        kind=CapabilityKind.WORKFLOW,
        name="Content Creation Workflow",
        description="选题分析 -> 循环扩写 -> 编辑整合。",
        tags=["content", "pipeline"],
    ),
    steps=[
        Step(
            id="analyze",
            capability=CapabilityRef(id="agent.content.topic_analyst"),
            input_mappings=[
                InputMapping(source="context.raw_idea", target_field="raw_idea"),
                InputMapping(source="context.audience", target_field="audience"),
            ],
        ),
        LoopStep(
            id="write_sections",
            capability=CapabilityRef(id="agent.content.angle_writer"),
            iterate_over="step.analyze.angles",
            item_input_mappings=[
                InputMapping(source="item", target_field="angle"),
                InputMapping(source="step.analyze.topic", target_field="topic"),
                InputMapping(source="context.audience", target_field="audience"),
            ],
            max_iterations=12,
        ),
        Step(
            id="edit",
            capability=CapabilityRef(id="agent.content.editor"),
            input_mappings=[
                InputMapping(source="step.analyze.topic", target_field="topic"),
                InputMapping(source="step.write_sections", target_field="sections"),
                InputMapping(source="context.target_length", target_field="target_length"),
            ],
        ),
    ],
    output_mappings=[
        InputMapping(source="step.analyze", target_field="analysis"),
        InputMapping(source="step.write_sections", target_field="sections"),
        InputMapping(source="step.edit", target_field="final"),
    ],
)
