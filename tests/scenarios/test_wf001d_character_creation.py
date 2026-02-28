"""场景测试：模拟 WF-001D 人物塑造子流程。"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from capability_runtime.protocol.agent import AgentSpec
from capability_runtime.protocol.capability import (
    CapabilityKind,
    CapabilityRef,
    CapabilityResult,
    CapabilitySpec,
    CapabilityStatus,
)
from capability_runtime.protocol.workflow import (
    InputMapping,
    LoopStep,
    Step,
    WorkflowSpec,
)
from capability_runtime.runtime import Runtime
from capability_runtime.config import RuntimeConfig


def _handler(spec: AgentSpec, input_dict: Dict[str, Any]) -> CapabilityResult:
    """按 Agent ID 返回不同结果的 mock（用于场景回归）。"""

    agent_id = spec.base.id

    if agent_id == "MA-013A":
        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output={
                "角色列表": [
                    {"定位": "女主-天真少女", "重要性": "核心"},
                    {"定位": "男主-冷面总裁", "重要性": "核心"},
                    {"定位": "反派-心机女", "重要性": "重要"},
                ],
            },
        )

    if agent_id == "MA-013":
        role = input_dict.get("角色定位", "未知")
        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output={
                "角色小传": f"{role}的完整人物设定...",
                "外貌": "...",
                "性格": "...",
            },
        )

    if agent_id == "MA-014":
        chars = input_dict.get("角色小传列表", [])
        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output={
                "关系图谱": f"共{len(chars)}个角色的关系...",
                "核心冲突": "三角关系",
            },
        )

    if agent_id == "MA-015":
        _ = input_dict.get("角色小传", {})
        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output={
                "视觉关键词": ["长发", "白裙", "月光下"],
                "风格": "日系",
            },
        )

    return CapabilityResult(
        status=CapabilityStatus.FAILED,
        error=f"Unknown agent: {agent_id}",
    )


@pytest.mark.asyncio
async def test_wf001d_full_flow():
    """
    WF-001D: MA-013A → [MA-013×3] → MA-014 → [MA-015×3]
    验证完整的人物塑造子流程。
    """
    agents = [
        AgentSpec(
            base=CapabilitySpec(
                id="MA-013A", kind=CapabilityKind.AGENT, name="角色定位规划师"
            )
        ),
        AgentSpec(
            base=CapabilitySpec(id="MA-013", kind=CapabilityKind.AGENT, name="单角色设计师"),
            loop_compatible=True,
        ),
        AgentSpec(
            base=CapabilitySpec(id="MA-014", kind=CapabilityKind.AGENT, name="角色关系架构师")
        ),
        AgentSpec(
            base=CapabilitySpec(id="MA-015", kind=CapabilityKind.AGENT, name="角色视觉化师"),
            loop_compatible=True,
        ),
    ]

    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-001D", kind=CapabilityKind.WORKFLOW, name="人物塑造子流程"),
        steps=[
            Step(
                id="plan",
                capability=CapabilityRef(id="MA-013A"),
                input_mappings=[
                    InputMapping(source="context.故事梗概", target_field="故事梗概")
                ],
            ),
            LoopStep(
                id="design",
                capability=CapabilityRef(id="MA-013"),
                iterate_over="step.plan.角色列表",
                item_input_mappings=[
                    InputMapping(source="item.定位", target_field="角色定位"),
                    InputMapping(source="context.故事梗概", target_field="故事梗概"),
                ],
                max_iterations=20,
            ),
            Step(
                id="relations",
                capability=CapabilityRef(id="MA-014"),
                input_mappings=[
                    InputMapping(source="step.design", target_field="角色小传列表")
                ],
            ),
            LoopStep(
                id="visual",
                capability=CapabilityRef(id="MA-015"),
                iterate_over="step.design",
                item_input_mappings=[
                    InputMapping(source="item", target_field="角色小传"),
                ],
                max_iterations=20,
            ),
        ],
        output_mappings=[
            InputMapping(source="step.design", target_field="角色小传列表"),
            InputMapping(source="step.relations", target_field="角色关系图谱"),
            InputMapping(source="step.visual", target_field="视觉关键词列表"),
        ],
    )

    rt = Runtime(RuntimeConfig(mode="mock", max_depth=10, mock_handler=_handler))
    for a in agents:
        rt.register(a)
    rt.register(wf)

    missing = rt.validate()
    assert not missing, f"Missing: {missing}"

    result = await rt.run(
        "WF-001D",
        input={"故事梗概": "霸道总裁爱上灰姑娘的故事"},
    )

    assert result.status == CapabilityStatus.SUCCESS
    assert (result.duration_ms or 0) > 0

    output = result.output
    assert "角色小传列表" in output
    assert len(output["角色小传列表"]) == 3

    assert "角色关系图谱" in output
    assert "3个角色" in output["角色关系图谱"]["关系图谱"]

    assert "视觉关键词列表" in output
    assert len(output["视觉关键词列表"]) == 3
