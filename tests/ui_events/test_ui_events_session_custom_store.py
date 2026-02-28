from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import pytest

from skills_runtime.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall
from skills_runtime.safety.approvals import ApprovalDecision, ApprovalProvider, ApprovalRequest

from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec, Runtime, RuntimeConfig
from capability_runtime.ui_events.store import AfterIdExpiredError, InMemoryRuntimeEventStore
from capability_runtime.ui_events.v1 import StreamLevel


class _ApproveAll(ApprovalProvider):
    async def request_approval(self, *, request: ApprovalRequest, timeout_ms: Optional[int] = None) -> ApprovalDecision:
        _ = (request, timeout_ms)
        return ApprovalDecision.APPROVED


class _CustomStore:
    def __init__(self) -> None:
        self._inner = InMemoryRuntimeEventStore(max_events=10_000)
        self.append_count = 0

    @property
    def min_rid(self) -> Optional[str]:
        return self._inner.min_rid

    @property
    def max_rid(self) -> Optional[str]:
        return self._inner.max_rid

    def append(self, ev) -> None:  # type: ignore[no-untyped-def]
        self.append_count += 1
        self._inner.append(ev)

    def read_after(self, *, after_id: Optional[str]):  # type: ignore[no-untyped-def]
        if after_id == "expired":
            raise AfterIdExpiredError(after_id="expired", min_rid=self.min_rid, max_rid=self.max_rid)
        return self._inner.read_after(after_id=after_id)


@pytest.mark.asyncio
async def test_start_ui_events_session_accepts_custom_store_injection(tmp_path: Path) -> None:
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

    store = _CustomStore()
    sess = rt.start_ui_events_session("agent.ui", input={}, level=StreamLevel.UI, store=store)

    out: List = []
    async for ev in sess.subscribe(after_id=None):
        out.append(ev)
        if ev.type == "tool.requested":
            break

    assert out
    assert store.append_count > 0, "expected custom store to be used for append()"

