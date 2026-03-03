from __future__ import annotations

import asyncio
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
async def test_ui_events_session_supports_after_id_exclusive_resume(tmp_path: Path) -> None:
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

    sess = rt.start_ui_events_session("agent.ui", input={}, level=StreamLevel.UI, store_max_events=10_000)

    first: List = []
    async for ev in sess.subscribe(after_id=None):
        first.append(ev)
        if ev.type == "tool.requested":
            break

    assert first
    after_id = first[-1].rid
    assert after_id is not None

    rest: List = []
    async for ev in sess.subscribe(after_id=after_id):
        rest.append(ev)
        if ev.type == "run.status" and ev.data.get("status") in {"completed", "failed", "cancelled", "pending"}:
            break

    assert rest, "expected resumed stream to yield events"
    assert all(e.rid != after_id for e in rest), "after_id must be exclusive"
    assert all(e.seq > first[-1].seq for e in rest), "resume must not duplicate old events"


@pytest.mark.asyncio
async def test_ui_events_session_after_id_expired_is_diagnostic(tmp_path: Path) -> None:
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

    sess = rt.start_ui_events_session("agent.ui", input={}, level=StreamLevel.UI, store_max_events=2)

    seen: List = []
    async for ev in sess.subscribe(after_id=None):
        seen.append(ev)
        if ev.type == "run.status" and ev.data.get("status") in {"completed", "failed", "cancelled", "pending"}:
            break

    assert seen and seen[0].rid is not None
    expired_after_id = seen[0].rid

    resumed: List = []
    async for ev in sess.subscribe(after_id=expired_after_id):
        resumed.append(ev)
        break

    assert resumed, "expected a diagnostic error event"
    assert resumed[0].type == "error"
    assert resumed[0].data.get("kind") == "after_id_expired"
    assert "message" in resumed[0].data
    # 结构化诊断字段（offline/real 一致；值允许为 None，但 key 必须存在）
    assert set(["after_id", "known_min_id", "known_max_id"]).issubset(set(resumed[0].data.keys()))
    assert resumed[0].data.get("after_id") == expired_after_id


@pytest.mark.asyncio
async def test_ui_events_session_after_id_expired_is_isolated_per_subscriber(tmp_path: Path) -> None:
    """
    回归护栏（D1）：同一 session 多订阅者中，一个订阅者 after_id 过期不应影响其它订阅者。
    """

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

    # store_max_events=2：确保很快裁剪，使早期 rid 过期，从而触发 after_id_expired
    sess = rt.start_ui_events_session("agent.ui", input={}, level=StreamLevel.UI, store_max_events=2)

    sub_a_seen: List = []
    sub_a_ready = asyncio.Event()

    async def _sub_a() -> None:
        async for ev in sess.subscribe(after_id=None):
            sub_a_seen.append(ev)
            if len(sub_a_seen) >= 3:
                sub_a_ready.set()

    task_a = asyncio.create_task(_sub_a())

    try:
        await asyncio.wait_for(sub_a_ready.wait(), timeout=5.0)
        assert sub_a_seen and sub_a_seen[0].rid is not None

        expired_after_id = sub_a_seen[0].rid

        sub_b_seen: List = []
        async for ev in sess.subscribe(after_id=expired_after_id):
            sub_b_seen.append(ev)
            break

        # 订阅者 B 应拿到 after_id_expired（本用例聚焦隔离语义；结构化字段由另一用例覆盖）
        assert sub_b_seen, "subscriber B should receive a diagnostic error"
        assert sub_b_seen[0].type == "error"
        assert sub_b_seen[0].data.get("kind") == "after_id_expired"

        # 等待订阅者 A 自然结束，避免遗留后台任务导致 teardown 噪音
        await asyncio.wait_for(task_a, timeout=10.0)
        assert sub_a_seen, "subscriber A should receive events"
        assert not any(
            (e.type == "error" and e.data.get("kind") == "after_id_expired") for e in sub_a_seen
        ), "after_id_expired must not be broadcast to other subscribers"
    finally:
        if not task_a.done():
            task_a.cancel()
