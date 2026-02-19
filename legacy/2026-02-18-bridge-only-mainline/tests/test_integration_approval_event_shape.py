from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import pytest

from agent_sdk.core.agent import Agent
from agent_sdk.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from agent_sdk.llm.fake import FakeChatBackend, FakeChatCall
from agent_sdk.safety.approvals import ApprovalDecision, ApprovalProvider, ApprovalRequest

from agently_skills_runtime.reporting.node_report import NodeReportBuilder


class _DenyApprovalProvider(ApprovalProvider):
    async def request_approval(self, *, request: ApprovalRequest, timeout_ms: Optional[int] = None) -> ApprovalDecision:
        return ApprovalDecision.DENIED


@pytest.mark.integration
def test_node_report_correlates_sdk_default_approval_events_by_step_id(tmp_path: Path):
    """
    真实 SDK Agent 事件形态：
    - approval_requested/decided payload 默认不含 call_id
    - 但与 tool_call_requested 同步共享 step_id
    NodeReportBuilder 必须能据此聚合到同一个 call_id。
    """

    backend = FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            LlmToolCall(call_id="c1", name="shell_exec", args={"argv": ["echo", "hi"]}),
                        ],
                    )
                ]
            ),
            FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="done"), ChatStreamEvent(type="completed")]),
        ]
    )

    agent = Agent(
        workspace_root=tmp_path,
        backend=backend,
        approval_provider=_DenyApprovalProvider(),
        human_io=None,
        env_vars={},
        config_paths=[],
    )

    events: List = list(agent.run_stream("run"))
    report = NodeReportBuilder().build(events=events)

    assert report.status in ("success", "failed", "incomplete", "needs_approval")
    # 至少有一条 tool evidence
    assert report.tool_calls
    t0 = report.tool_calls[0]
    assert t0.call_id == "c1"
    assert t0.requires_approval is True
    assert t0.approval_decision in (None, "denied", "approved", "approved_for_session")
