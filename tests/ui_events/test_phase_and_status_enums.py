from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Set

import pytest

from skills_runtime.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall
from skills_runtime.safety.approvals import ApprovalDecision, ApprovalProvider, ApprovalRequest

from agently_skills_runtime import AgentSpec, CapabilityKind, CapabilitySpec, Runtime, RuntimeConfig
from agently_skills_runtime.ui_events.v1 import StreamLevel


class _ApproveAll(ApprovalProvider):
    async def request_approval(self, *, request: ApprovalRequest, timeout_ms: Optional[int] = None) -> ApprovalDecision:
        _ = (request, timeout_ms)
        return ApprovalDecision.APPROVED


@pytest.mark.asyncio
async def test_phase_and_run_status_values_are_within_frozen_sets(tmp_path: Path) -> None:
    allowed_phases: Set[str] = {"IDLE", "THINKING", "TOOL_RUNNING", "WAITING_APPROVAL", "RUNNING", "REPORTING", "DONE"}
    allowed_run_status: Set[str] = {"running", "completed", "failed", "cancelled", "pending"}

    patch_text = "\n".join(["*** Begin Patch", "*** Add File: hello.txt", "+hello", "*** End Patch", ""]) + "\n"
    backend = FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[LlmToolCall(call_id="c1", name="apply_patch", args={"input": patch_text})],
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
    rt.register(AgentSpec(base=CapabilitySpec(id="agent.ui", kind=CapabilityKind.AGENT, name="AgentUI", description="离线：调用 apply_patch。")))

    out: List = []
    async for ev in rt.run_ui_events("agent.ui", input={}, level=StreamLevel.UI):
        out.append(ev)
        if ev.type == "run.status" and ev.data.get("status") != "running":
            break

    for e in out:
        if e.type == "node.phase":
            assert e.data.get("phase") in allowed_phases
        if e.type == "run.status":
            assert e.data.get("status") in allowed_run_status

