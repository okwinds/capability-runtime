from __future__ import annotations

from pathlib import Path
from typing import List, Optional

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
async def test_lite_level_does_not_emit_tool_or_approval_events(tmp_path: Path) -> None:
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
    async for ev in rt.run_ui_events("agent.ui", input={}, level=StreamLevel.LITE):
        out.append(ev)
        if ev.type == "run.status" and ev.data.get("status") != "running":
            break

    types = [e.type for e in out]
    assert "tool.requested" not in types
    assert "approval.requested" not in types
    assert "tool.finished" not in types


def test_raw_level_emits_raw_agent_event_summaries_without_secrets() -> None:
    from skills_runtime.core.contracts import AgentEvent

    from agently_skills_runtime.ui_events.projector import RuntimeUIEventProjector, _AgentCtx

    pj = RuntimeUIEventProjector(run_id="r1", level=StreamLevel.RAW)
    ctx = _AgentCtx(run_id="r1", capability_id="agent.x")

    ev = AgentEvent(
        type="tool_call_requested",
        timestamp="2026-02-10T00:00:00Z",
        run_id="r1",
        turn_id="t1",
        payload={"call_id": "c1", "name": "apply_patch", "arguments": {"secret": "TOPSECRET"}},
    )
    out = pj.on_agent_event(ev, ctx=ctx)
    assert any(e.type == "raw.agent_event" for e in out)
    assert "TOPSECRET" not in str([e.model_dump(by_alias=True) for e in out])

