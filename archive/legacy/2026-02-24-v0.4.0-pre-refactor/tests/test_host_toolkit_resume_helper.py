from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from agent_sdk.core.agent import Agent
from agent_sdk.core.contracts import AgentEvent
from agent_sdk.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from agent_sdk.llm.fake import FakeChatBackend, FakeChatCall

from capability_runtime.host_toolkit.resume import build_resume_replay_summary, load_agent_events_from_jsonl


def _ev(t: str, *, payload=None) -> AgentEvent:
    return AgentEvent(type=t, ts="2026-02-23T00:00:00Z", run_id="r1", payload=payload or {})


def test_resume_helper_builds_summary_without_leaking_tool_content(tmp_path: Path):
    secret_marker = "TOOL_SECRET_DO_NOT_LEAK"
    events = [
        _ev("run_started"),
        _ev(
            "tool_call_finished",
            payload={"call_id": "c1", "tool": "file_write", "result": {"ok": True, "data": {"content": secret_marker}}},
        ),
        _ev("approval_decided", payload={"approval_key": "k1", "decision": "approved_for_session"}),
        _ev("run_completed", payload={"final_output": "ok"}),
    ]
    p = tmp_path / "events.jsonl"
    p.write_text("\n".join([e.model_dump_json() for e in events]) + "\n", encoding="utf-8")

    loaded = load_agent_events_from_jsonl(events_path=p)
    _state, summary = build_resume_replay_summary(events=loaded)

    assert summary.events_count == 4
    assert summary.last_terminal_type == "run_completed"
    assert summary.approvals["approved_for_session_keys_count"] == 1
    assert secret_marker not in summary.model_dump_json()


@pytest.mark.integration
def test_explicit_initial_history_disables_sdk_auto_resume(tmp_path: Path):
    """
    上游行为回归护栏：
    - 同 run_id 存在 WAL 时，若显式传入 initial_history，则 SDK 不会注入 replay/summary resume。
    """

    backend = FakeChatBackend(
        calls=[
            FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="done"), ChatStreamEvent(type="completed")]),
        ]
    )

    # 第一次运行：生成 WAL
    agent1 = Agent(
        workspace_root=tmp_path,
        backend=backend,
        approval_provider=None,
        human_io=None,
        env_vars={},
        config_paths=[],
    )
    list(agent1.run_stream("run", run_id="r1"))

    overlay = tmp_path / "overlay.yaml"
    overlay.write_text("run:\n  resume_strategy: replay\n", encoding="utf-8")

    backend2 = FakeChatBackend(
        calls=[
            FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="ok"), ChatStreamEvent(type="completed")]),
        ]
    )
    agent2 = Agent(
        workspace_root=tmp_path,
        backend=backend2,
        approval_provider=None,
        human_io=None,
        env_vars={},
        config_paths=[overlay],
    )
    events2: List = list(agent2.run_stream("run2", run_id="r1", initial_history=[{"role": "user", "content": "hi"}]))

    started = next(e for e in events2 if e.type == "run_started")
    resume = started.payload.get("resume") or {}
    assert resume.get("enabled") in (False, None)

