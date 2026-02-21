"""场景测试：Skill inject_to 与 dispatch_rules。"""
from __future__ import annotations

from importlib import import_module

import pytest

from agently_skills_runtime.adapters.agent_adapter import AgentAdapter
from agently_skills_runtime.adapters.skill_adapter import SkillAdapter
from agently_skills_runtime.adapters.workflow_adapter import WorkflowAdapter
from agently_skills_runtime.protocol.capability import CapabilityKind, CapabilityStatus
from agently_skills_runtime.runtime.engine import CapabilityRuntime, RuntimeConfig


class RecordingRunner:
    """记录 AgentAdapter 调用参数，用于验证 skill 注入。"""

    def __init__(self) -> None:
        """初始化调用记录列表。"""
        self.calls: list[dict] = []

    async def __call__(self, task: str, *, initial_history=None):
        """保存 runner 调用并返回固定结构输出。"""
        self.calls.append({"task": task, "initial_history": initial_history})
        return {
            "tone_score": 7.1,
            "tone_label": "formal",
            "recommendations": ["Keep concise style"],
        }


def _build_runtime_for_injection(*, runner: RecordingRunner) -> CapabilityRuntime:
    """构建用于验证 inject_to 的 runtime。"""
    specs_mod = import_module("examples.00_prototype_validation.specs")

    runtime = CapabilityRuntime(config=RuntimeConfig(max_depth=10))
    runtime.set_adapter(CapabilityKind.AGENT, AgentAdapter(runner=runner))
    runtime.set_adapter(CapabilityKind.SKILL, SkillAdapter(workspace_root="."))
    runtime.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    runtime.register_many(specs_mod.ALL_SPECS)
    return runtime


def _build_runtime_for_dispatch() -> CapabilityRuntime:
    """构建用于验证 dispatch_rules 的 runtime（Agent 使用 mock）。"""
    specs_mod = import_module("examples.00_prototype_validation.specs")
    mock_mod = import_module("examples.00_prototype_validation.mock_adapter")

    runtime = CapabilityRuntime(config=RuntimeConfig(max_depth=10))
    runtime.set_adapter(CapabilityKind.AGENT, mock_mod.PrototypeMockAdapter())
    runtime.set_adapter(CapabilityKind.SKILL, SkillAdapter(workspace_root="."))
    runtime.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    runtime.register_many(specs_mod.ALL_SPECS)
    return runtime


@pytest.mark.asyncio
async def test_inject_to_skill_content_is_merged_without_duplication():
    """执行 tone-reviewer 时，rubric 文本应注入且不重复。"""
    runner = RecordingRunner()
    runtime = _build_runtime_for_injection(runner=runner)

    missing = runtime.validate()
    assert not missing

    result = await runtime.run(
        "tone-reviewer",
        run_id="run-inject",
        input={"content_summary": "Sample content summary."},
    )

    assert result.status == CapabilityStatus.SUCCESS
    assert len(runner.calls) == 1

    task_text = runner.calls[0]["task"]
    assert "Content Review Rubric" in task_text
    assert task_text.count("Content Review Rubric") == 1
    assert "请按以下格式输出 JSON" in task_text


@pytest.mark.asyncio
async def test_dispatch_rule_triggers_deep_investigator_only_when_condition_truthy():
    """critical_detected 为真时触发 dispatch；为假时不触发。"""
    runtime = _build_runtime_for_dispatch()

    missing = runtime.validate()
    assert not missing

    triggered = await runtime.run(
        "escalation-policy",
        run_id="run-dispatch-true",
        input={"target": "Evidence section"},
        context_bag={"critical_detected": True},
    )
    assert triggered.status == CapabilityStatus.SUCCESS
    dispatched = triggered.metadata.get("dispatched", [])
    assert len(dispatched) == 1
    assert dispatched[0]["target"] == "deep-investigator"
    assert dispatched[0]["result"]["severity_assessment"] == "high"

    not_triggered = await runtime.run(
        "escalation-policy",
        run_id="run-dispatch-false",
        input={"target": "Evidence section"},
        context_bag={"critical_detected": False},
    )
    assert not_triggered.status == CapabilityStatus.SUCCESS
    assert not not_triggered.metadata.get("dispatched")
