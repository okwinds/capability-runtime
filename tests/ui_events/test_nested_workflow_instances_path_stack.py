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
async def test_nested_workflow_tool_event_path_contains_outer_and_inner_workflow_scopes(tmp_path: Path) -> None:
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
    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="agent.inner",
                kind=CapabilityKind.AGENT,
                name="AgentInner",
                description="离线：调用 apply_patch。",
            )
        )
    )
    rt.register(
        WorkflowSpec(
            base=CapabilitySpec(id="wf.inner", kind=CapabilityKind.WORKFLOW, name="WFInner", description="inner wf"),
            steps=[Step(id="inner.s1", capability=CapabilityRef(id="agent.inner"))],
        )
    )
    rt.register(
        WorkflowSpec(
            base=CapabilitySpec(id="wf.outer", kind=CapabilityKind.WORKFLOW, name="WFOuter", description="outer wf"),
            steps=[Step(id="outer.s1", capability=CapabilityRef(id="wf.inner"))],
        )
    )

    out: List = []
    async for ev in rt.run_ui_events("wf.outer", input={}, level=StreamLevel.UI):
        out.append(ev)
        if ev.type == "run.status" and ev.data.get("status") in {"completed", "failed", "cancelled", "pending"}:
            break

    tool_events = [e for e in out if e.type == "tool.requested"]
    assert tool_events, "expected tool.requested in nested workflow ui stream"

    p = tool_events[0].path
    workflow_segs = [
        seg
        for seg in p
        if seg.kind == "workflow"
        and isinstance(getattr(seg, "ref", None), dict)
        and seg.ref.get("kind") == "workflow"
        and isinstance(seg.ref.get("id"), str)
    ]
    logical_ids = [seg.ref["id"] for seg in workflow_segs]

    # 嵌套链：必须同时出现 outer 与 inner 的 workflow 作用域（顺序 outer → inner）
    assert "wf.outer" in logical_ids
    assert "wf.inner" in logical_ids
    assert logical_ids.index("wf.outer") < logical_ids.index("wf.inner")

    # step 作用域：outer step 与 inner step 都应可见（用于归并与 drill-down）
    assert any(seg.kind == "step" and seg.id == "outer.s1" for seg in p)
    assert any(seg.kind == "step" and seg.id == "inner.s1" for seg in p)
