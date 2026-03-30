from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from skills_runtime.core.contracts import AgentEvent
from skills_runtime.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall
from skills_runtime.safety.approvals import ApprovalDecision, ApprovalProvider, ApprovalRequest

from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec, Runtime, RuntimeConfig
from capability_runtime.reporting.node_report import NodeReportBuilder
from capability_runtime.sdk_lifecycle import _sanitize_sdk_overlay_dict_for_loader


class _ApproveAll(ApprovalProvider):
    async def request_approval(self, *, request: ApprovalRequest, timeout_ms: Optional[int] = None) -> ApprovalDecision:
        _ = (request, timeout_ms)
        return ApprovalDecision.APPROVED


def _ev(t: str, *, payload: dict | None = None, step_id: str | None = None) -> AgentEvent:
    return AgentEvent(
        type=t,
        timestamp="2026-03-31T00:00:00Z",
        run_id="r1",
        turn_id="t1",
        step_id=step_id,
        payload=payload or {},
    )


def test_sanitizer_does_not_inject_sandbox_defaults_when_field_is_missing() -> None:
    sanitized, issues = _sanitize_sdk_overlay_dict_for_loader({"sandbox": {"default_policy": "restricted"}, "skills": {}})

    assert sanitized == {"sandbox": {"default_policy": "restricted"}, "skills": {}}
    assert issues == []


def test_node_report_tool_safety_summary_records_only_enum_string() -> None:
    report = NodeReportBuilder().build(
        events=[
            _ev("run_started"),
            _ev(
                "tool_call_requested",
                step_id="s1",
                payload={
                    "call_id": "c1",
                    "name": "file_write",
                    "arguments": {
                        "path": "out.txt",
                        "content": "secret",
                        "sandbox_permissions": "require_escalated",
                    },
                },
            ),
            _ev("approval_requested", step_id="s1", payload={"tool": "file_write", "approval_key": "k1"}),
            _ev("run_cancelled", payload={"message": "waiting", "wal_locator": "wal.jsonl"}),
        ]
    )

    assert report.tool_calls[0].requires_approval is True
    assert report.meta["tool_safety"] == {
        "c1": {
            "sandbox_permissions": "require_escalated",
            "source": "tool_call_requested",
        }
    }
    assert "secret" not in str(report.meta["tool_safety"])


def test_node_report_tool_safety_can_recover_enum_from_approval_request_payload() -> None:
    report = NodeReportBuilder().build(
        events=[
            _ev("run_started"),
            _ev(
                "tool_call_requested",
                step_id="s1",
                payload={"call_id": "c1", "name": "file_write", "arguments": {"path": "out.txt", "content": "secret"}},
            ),
            _ev(
                "approval_requested",
                step_id="s1",
                payload={
                    "tool": "file_write",
                    "approval_key": "k1",
                    "request": {"sandbox_permissions": "require_escalated", "path": "out.txt"},
                },
            ),
            _ev("run_cancelled", payload={"message": "waiting", "wal_locator": "wal.jsonl"}),
        ]
    )

    assert report.meta["tool_safety"] == {
        "c1": {
            "sandbox_permissions": "require_escalated",
            "source": "approval_requested",
        }
    }
    assert "out.txt" not in str(report.meta["tool_safety"])


@pytest.mark.asyncio
async def test_runtime_preserves_per_call_sandbox_permissions_without_bridge_rewrite(tmp_path: Path) -> None:
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
                                args={
                                    "path": "out.txt",
                                    "content": "hello\n",
                                    "sandbox_permissions": "require_escalated",
                                },
                            )
                        ],
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
                id="agent.sandbox",
                kind=CapabilityKind.AGENT,
                name="SandboxAgent",
                description="离线：使用 file_write 并携带 sandbox_permissions。",
            )
        )
    )

    terminal = await rt.run("agent.sandbox", input={})

    assert terminal.status.value == "success"
    assert terminal.node_report is not None
    tool = next(t for t in (terminal.node_report.tool_calls or []) if t.call_id == "c1")
    assert tool.name == "file_write"
    assert tool.requires_approval is True
    assert (terminal.node_report.meta.get("tool_safety") or {}).get("c1") == {
        "sandbox_permissions": "require_escalated",
        "source": "tool_call_requested",
    }
    assert Path(str(terminal.node_report.events_path)).exists()
