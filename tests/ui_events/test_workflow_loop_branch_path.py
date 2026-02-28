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
    LoopStep,
    Runtime,
    RuntimeConfig,
    WorkflowSpec,
)
from capability_runtime.ui_events.v1 import StreamLevel


class _ApproveAll(ApprovalProvider):
    async def request_approval(self, *, request: ApprovalRequest, timeout_ms: Optional[int] = None) -> ApprovalDecision:
        _ = (request, timeout_ms)
        return ApprovalDecision.APPROVED


@pytest.mark.asyncio
async def test_loop_step_iterations_have_branch_path_segments_best_effort(tmp_path: Path) -> None:
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
            FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="done1"), ChatStreamEvent(type="completed")]),
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[LlmToolCall(call_id="c2", name="apply_patch", args={"input": patch_text})],
                        finish_reason="tool_calls",
                    ),
                    ChatStreamEvent(type="completed", finish_reason="tool_calls"),
                ]
            ),
            FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="done2"), ChatStreamEvent(type="completed")]),
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
            base=CapabilitySpec(id="wf.loop", kind=CapabilityKind.WORKFLOW, name="WFLoop", description="循环 step"),
            steps=[
                LoopStep(
                    id="loop1",
                    capability=CapabilityRef(id="agent.ui"),
                    iterate_over="context.items",
                    max_iterations=10,
                    collect_as="results",
                )
            ],
        )
    )

    out: List = []
    async for ev in rt.run_ui_events("wf.loop", input={"items": [1, 2]}, level=StreamLevel.UI):
        out.append(ev)
        if ev.type == "run.status" and ev.data.get("status") != "running":
            break

    tool_events = [e for e in out if e.type == "tool.requested"]
    assert tool_events
    branch_ids = []
    for e in tool_events:
        for seg in e.path:
            if seg.kind == "branch":
                branch_ids.append(seg.id)
                break
    assert branch_ids, "expected at least one branch segment in loop iterations"
    assert len(set(branch_ids)) >= 2, "expected multiple iterations to map to distinct branch ids (best-effort)"

