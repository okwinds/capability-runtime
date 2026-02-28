from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import List, Optional

import pytest

from skills_runtime.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall
from skills_runtime.safety.approvals import ApprovalDecision, ApprovalProvider, ApprovalRequest

from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec, Runtime, RuntimeConfig
from capability_runtime.ui_events.v1 import StreamLevel


class _ApproveAll(ApprovalProvider):
    async def request_approval(self, *, request: ApprovalRequest, timeout_ms: Optional[int] = None) -> ApprovalDecision:
        _ = (request, timeout_ms)
        return ApprovalDecision.APPROVED


@pytest.mark.asyncio
async def test_run_ui_events_agent_emits_tool_and_approval_summaries_without_secrets(tmp_path: Path) -> None:
    patch_text = "\n".join(["*** Begin Patch", "*** Add File: hello.txt", "+hello", "*** End Patch", ""]) + "\n"

    backend = FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[LlmToolCall(call_id="c1", name="apply_patch", args={"input": patch_text, "secret": "TOPSECRET"})],
                        finish_reason="tool_calls",
                    ),
                    ChatStreamEvent(type="completed", finish_reason="tool_calls"),
                ]
            ),
            FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="done"), ChatStreamEvent(type="completed")]),
        ]
    )

    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=tmp_path,
            sdk_config_paths=[],
            preflight_mode="off",
            sdk_backend=backend,
            approval_provider=_ApproveAll(),
        )
    )
    rt.register(
        AgentSpec(
            base=CapabilitySpec(id="agent.ui", kind=CapabilityKind.AGENT, name="AgentUI", description="离线：调用 apply_patch。"),
        )
    )

    out: List = []
    async for ev in rt.run_ui_events("agent.ui", input={}, level=StreamLevel.UI):
        out.append(ev)
        if ev.type == "run.status" and ev.data.get("status") in {"completed", "failed", "cancelled", "pending"}:
            break

    types = [e.type for e in out]
    assert "tool.requested" in types
    assert "approval.requested" in types
    assert "tool.finished" in types
    assert any(e.type == "node.finished" and any(seg.kind == "agent" for seg in e.path) for e in out)
    assert any(
        e.type == "node.phase"
        and e.data.get("phase") == "DONE"
        and any(seg.kind == "agent" for seg in e.path)
        for e in out
    )
    assert any(
        e.type == "node.phase"
        and e.data.get("phase") == "REPORTING"
        and any(seg.kind == "agent" for seg in e.path)
        for e in out
    ), "expected best-effort REPORTING phase for agent node before terminal"

    # 最小披露：不应出现明文 args/secret
    tool_req = next(e for e in out if e.type == "tool.requested")
    assert "args_summary" in tool_req.data
    assert "sha256" in tool_req.data["args_summary"]
    assert "secret" not in (tool_req.data.get("args") or {})
    assert "TOPSECRET" not in str(tool_req.model_dump(by_alias=True))
