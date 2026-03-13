"""
客服质检 Agent 测试：skills-first + run_structured + NodeReport 审计证据。

运行：
  pytest tests/test_qa_agent.py -v

规格入口：docs/specs/qa-agent-v1.md
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest

from skills_runtime.llm.chat_sse import ChatStreamEvent
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall

from capability_runtime import (
    AgentIOSchema,
    AgentSpec,
    CapabilityKind,
    CapabilitySpec,
    CapabilityStatus,
    Runtime,
    RuntimeConfig,
)


def _qa_output_schema() -> AgentIOSchema:
    """质检报告输出 Schema。"""
    return AgentIOSchema(
        fields={
            "conversation_id": "str",
            "overall_score": "float",
            "dimensions": "list",
            "critical_issues": "list",
            "passed": "bool",
        },
        required=["conversation_id", "overall_score", "passed"],
    )


def _build_qa_agent_spec() -> AgentSpec:
    """构建客服质检 Agent 声明。"""
    return AgentSpec(
        base=CapabilitySpec(
            id="agent.qa.quality_check",
            kind=CapabilityKind.AGENT,
            name="QualityCheck",
            description="客服对话质检",
        ),
        skills=["qa_checker"],
        output_schema=_qa_output_schema(),
    )


def _mk_runtime(
    tmp_path: Path,
    *,
    events: List[ChatStreamEvent],
) -> Runtime:
    backend = FakeChatBackend(calls=[FakeChatCall(events=events)])
    return Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=tmp_path,
            sdk_backend=backend,
            preflight_mode="off",
        )
    )


def _qa_result_json() -> str:
    """模拟质检结果 JSON。"""
    return json.dumps(
        {
            "conversation_id": "conv-001",
            "overall_score": 85.5,
            "dimensions": [
                {"name": "服务态度", "score": 90, "issues": [], "suggestions": []},
                {"name": "业务准确性", "score": 80, "issues": ["退款政策解释不够准确"], "suggestions": []},
            ],
            "critical_issues": [],
            "passed": True,
        },
        ensure_ascii=False,
    )


class TestQAAgentSpec:
    """测试 AgentSpec 声明。"""

    def test_qa_agent_spec_has_output_schema(self) -> None:
        """AgentSpec 应包含 output_schema。"""
        spec = _build_qa_agent_spec()
        assert spec.output_schema is not None
        assert "conversation_id" in spec.output_schema.fields
        assert "overall_score" in spec.output_schema.fields
        assert "passed" in spec.output_schema.fields
        assert "conversation_id" in spec.output_schema.required

    def test_qa_agent_spec_declares_skills(self) -> None:
        """AgentSpec 应声明 skills。"""
        spec = _build_qa_agent_spec()
        assert "qa_checker" in spec.skills


class TestQAAgentRunStructured:
    """测试 run_structured 入口。"""

    @pytest.mark.asyncio
    async def test_run_structured_returns_json(self, tmp_path: Path) -> None:
        """run_structured 应返回结构化 JSON。"""
        rt = _mk_runtime(tmp_path, events=[ChatStreamEvent(type="text_delta", text=_qa_result_json()), ChatStreamEvent(type="completed")])
        rt.register(_build_qa_agent_spec())

        result = await rt.run_structured("agent.qa.quality_check", input={"conversation_id": "conv-001", "messages": []})

        assert result.status == CapabilityStatus.SUCCESS
        assert isinstance(result.output, dict)
        assert result.output.get("conversation_id") == "conv-001"
        assert result.output.get("overall_score") == 85.5
        assert result.output.get("passed") is True

    @pytest.mark.asyncio
    async def test_run_structured_node_report_preserved(self, tmp_path: Path) -> None:
        """NodeReport 应完整保留作为审计证据。"""
        rt = _mk_runtime(tmp_path, events=[ChatStreamEvent(type="text_delta", text=_qa_result_json()), ChatStreamEvent(type="completed")])
        rt.register(_build_qa_agent_spec())

        result = await rt.run_structured("agent.qa.quality_check", input={"conversation_id": "conv-001", "messages": []})

        assert result.node_report is not None
        assert result.node_report.status == "success"
        assert result.node_report.run_id  # 非空

    @pytest.mark.asyncio
    async def test_run_structured_fail_on_missing_required_field(self, tmp_path: Path) -> None:
        """缺少必填字段时应失败。"""
        invalid_json = json.dumps({"conversation_id": "conv-001", "overall_score": 85.5})  # 缺少 passed
        rt = _mk_runtime(tmp_path, events=[ChatStreamEvent(type="text_delta", text=invalid_json), ChatStreamEvent(type="completed")])
        rt.register(_build_qa_agent_spec())

        result = await rt.run_structured("agent.qa.quality_check", input={"conversation_id": "conv-001", "messages": []})

        assert result.status == CapabilityStatus.FAILED
        assert result.error_code == "STRUCTURED_OUTPUT_INVALID"


class TestQAAgentMockMode:
    """测试 mock 模式基本流程。"""

    @pytest.mark.asyncio
    async def test_mock_mode_basic(self, tmp_path: Path) -> None:
        """mock 模式基本流程测试。"""
        # 使用 sdk_native + FakeChatBackend 模拟 mock 行为
        rt = _mk_runtime(tmp_path, events=[ChatStreamEvent(type="text_delta", text=_qa_result_json()), ChatStreamEvent(type="completed")])
        rt.register(_build_qa_agent_spec())

        result = await rt.run("agent.qa.quality_check", input={"conversation_id": "conv-001", "messages": []})

        assert result.status == CapabilityStatus.SUCCESS
        assert result.output is not None
        # NodeReport 包含结构化输出摘要
        assert result.node_report is not None
        structured = result.node_report.meta.get("structured_output", {})
        assert structured.get("ok") is True
