from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import pytest

from skills_runtime.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall
from skills_runtime.safety.approvals import ApprovalDecision, ApprovalProvider, ApprovalRequest

from capability_runtime import (
    AgentSpec,
    CapabilityKind,
    CapabilityRef,
    CapabilitySpec,
    Runtime,
    RuntimeConfig,
    Step,
    WorkflowSpec,
)
from capability_runtime.ui_events.v1 import StreamLevel


class _ApproveAll(ApprovalProvider):
    async def request_approval(self, *, request: ApprovalRequest, timeout_ms: Optional[int] = None) -> ApprovalDecision:
        _ = (request, timeout_ms)
        return ApprovalDecision.APPROVED


@pytest.mark.asyncio
async def test_workflow_ui_level_step_window_includes_tool_events_with_step_path(tmp_path: Path) -> None:
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
    rt.register(
        WorkflowSpec(
            base=CapabilitySpec(id="wf.ui", kind=CapabilityKind.WORKFLOW, name="WFUI", description="单步 workflow"),
            steps=[Step(id="s1", capability=CapabilityRef(id="agent.ui"))],
        )
    )

    out: List = []
    async for ev in rt.run_ui_events("wf.ui", input={}, level=StreamLevel.UI):
        out.append(ev)
        if ev.type == "run.status" and ev.data.get("status") in {"completed", "failed", "cancelled", "pending"}:
            break

    tool_events = [e for e in out if e.type == "tool.requested"]
    assert tool_events, "expected tool.requested to appear in workflow ui stream"

    # deep stream 关键点：tool 事件必须能归并到 workflow/step path（避免 step 内黑洞）
    p = tool_events[0].path
    assert any(seg.kind == "step" and seg.id == "s1" for seg in p)
    assert any(
        seg.kind == "workflow"
        and isinstance(getattr(seg, "ref", None), dict)
        and seg.ref.get("kind") == "workflow"
        and seg.ref.get("id") == "wf.ui"
        for seg in p
    )
