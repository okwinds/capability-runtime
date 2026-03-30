from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import AsyncIterator, List, Optional

import pytest

from skills_runtime.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall
from skills_runtime.safety.approvals import ApprovalDecision, ApprovalProvider, ApprovalRequest

from capability_runtime import AgentIOSchema, AgentSpec, CapabilityKind, CapabilitySpec, Runtime, RuntimeConfig
from capability_runtime.ui_events.v1 import StreamLevel


class _ApproveAll(ApprovalProvider):
    async def request_approval(self, *, request: ApprovalRequest, timeout_ms: Optional[int] = None) -> ApprovalDecision:
        _ = (request, timeout_ms)
        return ApprovalDecision.APPROVED


class _UsageAwareBackend:
    """测试用 backend：通过 bridge usage sink 上抬 usage，再返回最小完成流。"""

    async def stream_chat(self, request) -> AsyncIterator[ChatStreamEvent]:  # type: ignore[override]
        sink = None
        if isinstance(getattr(request, "extra", None), dict):
            candidate = request.extra.get("_caprt_usage_sink")
            if callable(candidate):
                sink = candidate
        if sink is not None:
            sink({"model": "usage-test-model", "input_tokens": 11, "output_tokens": 7, "total_tokens": 18})
        yield ChatStreamEvent(type="text_delta", text="done")
        yield ChatStreamEvent(type="completed", finish_reason="stop")


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


@pytest.mark.asyncio
async def test_run_ui_events_agent_emits_metrics_when_bridge_usage_available(tmp_path: Path) -> None:
    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=tmp_path,
            sdk_config_paths=[],
            preflight_mode="off",
            sdk_backend=_UsageAwareBackend(),
        )
    )
    rt.register(
        AgentSpec(
            base=CapabilitySpec(id="agent.metrics", kind=CapabilityKind.AGENT, name="AgentMetrics", description="离线：usage bridge。"),
        )
    )

    terminal = await rt.run("agent.metrics", input={})
    assert terminal.node_report is not None
    assert terminal.node_report.usage is not None
    assert terminal.node_report.usage.model == "usage-test-model"
    assert terminal.node_report.usage.input_tokens == 11
    assert terminal.node_report.usage.output_tokens == 7
    assert terminal.node_report.usage.total_tokens == 18

    out: List = []
    async for ev in rt.run_ui_events("agent.metrics", input={}, level=StreamLevel.UI):
        out.append(ev)
        if ev.type == "run.status" and ev.data.get("status") in {"completed", "failed", "cancelled", "pending"}:
            break

    metrics = next(e for e in out if e.type == "metrics")
    assert metrics.data == {
        "model": "usage-test-model",
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
    }


@pytest.mark.asyncio
async def test_run_ui_events_terminal_exposes_structured_output_summary_when_present(tmp_path: Path) -> None:
    backend = FakeChatBackend(
        calls=[FakeChatCall(events=[ChatStreamEvent(type="text_delta", text='{"title":"A","summary":"B"}'), ChatStreamEvent(type="completed")])]
    )

    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=tmp_path,
            sdk_config_paths=[],
            preflight_mode="off",
            sdk_backend=backend,
            output_validation_mode="warn",
        )
    )
    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="agent.structured-ui",
                kind=CapabilityKind.AGENT,
                name="AgentStructuredUI",
                description="离线：输出结构化 JSON。",
            ),
            output_schema=AgentIOSchema(
                fields={"title": "str", "summary": "str"},
                required=["title", "summary"],
            ),
        )
    )

    terminal = None
    async for ev in rt.run_ui_events("agent.structured-ui", input={}, level=StreamLevel.UI):
        if ev.type == "run.status" and ev.data.get("status") in {"completed", "failed", "cancelled", "pending"}:
            terminal = ev
            break

    assert terminal is not None
    so = terminal.data.get("structured_output")
    assert isinstance(so, dict), terminal
    assert so.get("ok") is True
    assert so.get("schema_id") == "capability-runtime.agent_output_schema.v1:agent.structured-ui"
    assert so.get("required") == ["title", "summary"]


@pytest.mark.asyncio
async def test_run_ui_events_agent_emits_pending_terminal_for_waiting_human(tmp_path: Path) -> None:
    backend = FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            LlmToolCall(
                                call_id="c1",
                                name="ask_human",
                                args={"question": "需要你确认下一步"},
                            )
                        ],
                        finish_reason="tool_calls",
                    ),
                    ChatStreamEvent(type="completed", finish_reason="tool_calls"),
                ]
            )
        ]
    )

    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=tmp_path,
            sdk_config_paths=[],
            preflight_mode="off",
            sdk_backend=backend,
            human_io=None,
        )
    )
    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="agent.waiting-human",
                kind=CapabilityKind.AGENT,
                name="AgentWaitingHuman",
                description="离线：触发 ask_human 等待终态。",
            ),
        )
    )

    out: List = []
    async for ev in rt.run_ui_events("agent.waiting-human", input={}, level=StreamLevel.UI):
        out.append(ev)
        if ev.type == "run.status" and ev.data.get("status") in {"completed", "failed", "cancelled", "pending"}:
            break

    assert any(
        e.type == "node.finished"
        and e.data.get("status") == "pending"
        and any(seg.kind == "agent" for seg in e.path)
        for e in out
    )
    assert any(
        e.type == "node.phase"
        and e.data.get("phase") == "DONE"
        and any(seg.kind == "agent" for seg in e.path)
        for e in out
    )
    terminal = next(e for e in reversed(out) if e.type == "run.status")
    assert terminal.data.get("status") == "pending"
    host_runtime = terminal.data.get("host_runtime")
    assert host_runtime == {
        "status": "waiting_human",
        "wait_kind": "host_input",
        "run_id": terminal.run_id,
        "node_status": "needs_approval",
        "events_path": terminal.evidence.events_path if terminal.evidence else None,
        "tool_name": "ask_human",
        "call_id": "c1",
        "workflow_id": None,
        "workflow_instance_id": None,
        "step_id": None,
        "approval_key": None,
        "message_kind": "ask_human",
        "message_preview": host_runtime["message_preview"],
        "resume_state": {},
    }
    assert isinstance(host_runtime["message_preview"], str)
    assert host_runtime["message_preview"]
    assert "question" not in host_runtime["message_preview"]
