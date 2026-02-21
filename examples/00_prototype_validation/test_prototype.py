"""原型目录离线回归（无需 FastAPI/uvicorn）。"""
from __future__ import annotations

from importlib import import_module

import pytest

from agently_skills_runtime.adapters.skill_adapter import SkillAdapter
from agently_skills_runtime.protocol.capability import CapabilityKind, CapabilityStatus
from agently_skills_runtime.runtime.engine import CapabilityRuntime, RuntimeConfig


def _build_runtime(event_bus):
    """组装原型 runtime（mock agent + instrumented workflow）。"""
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


@pytest.mark.asyncio
async def test_mock_pipeline_neutral_score_is_stable():
    """neutral 场景固定分数断言。"""
    instrumented_mod = import_module("examples.00_prototype_validation.instrumented")
    bus = instrumented_mod.RunEventBus()
    runtime = _build_runtime(bus)

    result = await runtime.run(
        "content-analysis",
        run_id="prototype-selftest",
        context_bag={
            "raw_content": "Neutral sample content",
            "analysis_depth": "standard",
            "overall_severity": "neutral",
            "critical_detected": False,
        },
    )

    assert result.status == CapabilityStatus.SUCCESS
    assert result.output["final_report"]["overall_score"] == 6.5
    assert any(e["event"] == "workflow_complete" for e in bus.get_history("prototype-selftest"))
