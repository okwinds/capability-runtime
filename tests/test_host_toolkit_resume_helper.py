from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from skills_runtime.core.agent import Agent
from skills_runtime.core.contracts import AgentEvent
from skills_runtime.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall

from capability_runtime.host_toolkit.resume import (
    build_host_resume_state,
    build_resume_replay_summary,
    load_agent_events_from_jsonl,
    load_agent_events_from_locator,
)


def _ev(t: str, *, payload=None) -> AgentEvent:
    return AgentEvent(type=t, timestamp="2026-02-23T00:00:00Z", run_id="r1", payload=payload or {})


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
    host_state = build_host_resume_state(events=loaded)

    assert summary.events_count == 4
    assert summary.last_terminal_type == "run_completed"
    assert summary.approvals["approved_for_session_keys_count"] == 1
    assert summary.tool_calls.requested_count == 0
    assert summary.tool_calls.finished_count == 1
    assert summary.tool_calls.pending_count == 0
    assert summary.tool_calls.latest_pending_call_ids == []
    assert summary.tool_calls.latest_tool_calls == [
        {
            "call_id": "c1",
            "name": "file_write",
            "step_id": None,
            "status": "finished",
        }
    ]
    assert host_state.tool_calls == summary.tool_calls
    assert secret_marker not in summary.model_dump_json()


def test_load_agent_events_from_jsonl_rejects_wal_locator_with_clear_message():
    with pytest.raises(ValueError, match="wal_backend is required for wal locator"):
        load_agent_events_from_jsonl(events_path="wal://r1")

    # 允许 `#fragment`，但仍应明确拒绝 `wal://...` 作为 filesystem path。
    with pytest.raises(ValueError, match="wal_backend is required for wal locator"):
        load_agent_events_from_jsonl(events_path="wal://r1#run_id=r1")


def test_resume_helper_builds_summary_from_wal_locator_backend() -> None:
    raw = "\n".join(
        [
            _ev("run_started").model_dump_json(),
            _ev("tool_call_finished", payload={"call_id": "c1", "tool": "file_write", "result": {"ok": True}}).model_dump_json(),
            _ev("run_completed", payload={"final_output": "ok"}).model_dump_json(),
            "",
        ]
    )

    class _WalBackend:
        def read_text(self, locator: str) -> str:
            assert locator == "wal://run/1"
            return raw

    loaded = load_agent_events_from_locator(events_path="wal://run/1", wal_backend=_WalBackend())
    _state, summary = build_resume_replay_summary(events=loaded)

    assert summary.tool_calls.finished_count == 1


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
