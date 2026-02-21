"""场景测试：原型验证 Mock 管线与事件流。"""
from __future__ import annotations

from importlib import import_module

import pytest

from agently_skills_runtime.adapters.skill_adapter import SkillAdapter
from agently_skills_runtime.protocol.capability import CapabilityKind, CapabilityStatus
from agently_skills_runtime.runtime.engine import CapabilityRuntime, RuntimeConfig


def _expected_capability_ids() -> set[str]:
    """返回原型必须注册的 13 个能力 ID 集合。"""
    return {
        "review-rubric",
        "escalation-policy",
        "content-parser",
        "section-analyzer",
        "tone-reviewer",
        "fact-checker",
        "deep-investigator",
        "positive-summarizer",
        "critical-reporter",
        "neutral-summarizer",
        "report-compiler",
        "parallel-review",
        "content-analysis",
    }


def _build_runtime(event_bus):
    """构造用于离线回归的 runtime（Mock Agent + Instrumented Workflow）。"""
    specs_mod = import_module("examples.00_prototype_validation.specs")
    mock_mod = import_module("examples.00_prototype_validation.mock_adapter")
    instrumented_mod = import_module("examples.00_prototype_validation.instrumented")

    runtime = CapabilityRuntime(config=RuntimeConfig(max_depth=10))
    runtime.set_adapter(
        CapabilityKind.AGENT,
        instrumented_mod.InstrumentedAdapter(
            inner=mock_mod.PrototypeMockAdapter(),
            event_bus=event_bus,
        ),
    )
    runtime.set_adapter(
        CapabilityKind.SKILL,
        instrumented_mod.InstrumentedAdapter(
            inner=SkillAdapter(workspace_root="."),
            event_bus=event_bus,
        ),
    )
    runtime.set_adapter(
        CapabilityKind.WORKFLOW,
        instrumented_mod.InstrumentedWorkflowAdapter(event_bus=event_bus),
    )
    runtime.register_many(specs_mod.ALL_SPECS)
    return runtime


def test_capability_registry_contains_exact_13_specs():
    """校验 13 个能力声明完整且无漂移。"""
    specs_mod = import_module("examples.00_prototype_validation.specs")

    assert len(specs_mod.ALL_SPECS) == 13
    ids = {spec.base.id for spec in specs_mod.ALL_SPECS}
    assert ids == _expected_capability_ids()


@pytest.mark.asyncio
async def test_mock_pipeline_emits_required_events_and_expected_output():
    """neutral 场景：校验输出链路与关键事件类型/顺序。"""
    instrumented_mod = import_module("examples.00_prototype_validation.instrumented")
    bus = instrumented_mod.RunEventBus()
    runtime = _build_runtime(bus)

    missing = runtime.validate()
    assert not missing

    run_id = "run-neutral-mock"
    result = await runtime.run(
        "content-analysis",
        run_id=run_id,
        context_bag={
            "raw_content": "A sample article with intro, argument, evidence.",
            "analysis_depth": "standard",
            "overall_severity": "neutral",
            "critical_detected": False,
        },
    )

    assert result.status == CapabilityStatus.SUCCESS
    output = result.output
    assert output["final_report"]["overall_score"] == 6.5
    assert len(output["section_analyses"]) == 3
    assert len(output["review_results"]["review_results"]) == 2
    assert "areas_for_improvement" in output["severity_summary"]

    history = bus.get_history(run_id)
    assert history, "event history should not be empty"

    allowed_events = {
        "step_start",
        "step_complete",
        "loop_item",
        "parallel_start",
        "branch_complete",
        "conditional_route",
        "workflow_complete",
        "error",
    }
    seen_events = {record["event"] for record in history}
    assert {
        "step_start",
        "step_complete",
        "loop_item",
        "parallel_start",
        "branch_complete",
        "conditional_route",
        "workflow_complete",
    }.issubset(seen_events)
    assert seen_events.issubset(allowed_events)

    parse_start_idx = next(
        index
        for index, record in enumerate(history)
        if record["event"] == "step_start"
        and record["data"].get("step_id") == "parse"
    )
    parse_complete_idx = next(
        index
        for index, record in enumerate(history)
        if record["event"] == "step_complete"
        and record["data"].get("step_id") == "parse"
    )
    assert parse_start_idx < parse_complete_idx

    loop_items = [
        record
        for record in history
        if record["event"] == "loop_item"
        and record["data"].get("step_id") == "section-loop"
    ]
    assert len(loop_items) == 3

    route = next(
        record
        for record in history
        if record["event"] == "conditional_route"
        and record["data"].get("step_id") == "route-by-severity"
    )
    assert route["data"]["selected_branch"] == "default"

    workflow_complete = next(
        record
        for record in history
        if record["event"] == "workflow_complete"
        and record["data"].get("workflow_id") == "content-analysis"
    )
    assert workflow_complete["data"]["status"] == CapabilityStatus.SUCCESS.value

    for record in history:
        assert record["data"]["run_id"] == run_id
        assert record["data"].get("ts"), "each event should carry timestamp"
