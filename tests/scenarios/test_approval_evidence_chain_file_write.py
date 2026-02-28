from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import pytest

from skills_runtime.core.agent import Agent
from skills_runtime.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall
from skills_runtime.safety.approvals import ApprovalDecision, ApprovalProvider, ApprovalRequest

from capability_runtime.reporting.node_report import NodeReportBuilder


class _ApproveProvider(ApprovalProvider):
    async def request_approval(self, *, request: ApprovalRequest, timeout_ms: Optional[int] = None) -> ApprovalDecision:
        return ApprovalDecision.APPROVED


def test_approval_evidence_chain_for_file_write_is_auditable_and_no_content_leak(tmp_path: Path):
    """
    场景回归护栏：
    - file_write 在 safety.mode=ask 下必须触发 approvals（approval_requested/decided）；
    - NodeReportBuilder 必须能聚合 tool_calls 的审批证据链；
    - WAL/events.jsonl 不得包含 file_write.content 明文（只允许 bytes/sha256 摘要）。
    """

    secret_content = "FILE_WRITE_CONTENT_SECRET_DO_NOT_LEAK"
    backend = FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            LlmToolCall(
                                call_id="c1",
                                name="file_write",
                                args={"path": "out.txt", "content": secret_content},
                            ),
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
        approval_provider=_ApproveProvider(),
        human_io=None,
        env_vars={},
        config_paths=[],
    )

    events: List = list(agent.run_stream("write file", run_id="r1"))
    report = NodeReportBuilder().build(events=events)

    assert report.status == "success"
    assert report.tool_calls, "expected at least one tool_call report"
    t0 = report.tool_calls[0]
    assert t0.call_id == "c1"
    assert t0.name == "file_write"
    assert t0.requires_approval is True
    assert t0.approval_decision == "approved"
    assert t0.approval_reason in ("provider", "cached", "timeout", "no_provider", None)

    assert report.events_path, "expected events_path from SDK WAL"
    wal_text = Path(report.events_path).read_text(encoding="utf-8")
    assert secret_content not in wal_text
