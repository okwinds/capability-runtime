from __future__ import annotations

from skills_runtime.core.contracts import AgentEvent

from capability_runtime.host_toolkit.resume import build_host_resume_state, build_resume_replay_summary
from capability_runtime.reporting.node_report import NodeReportBuilder


def _ev(t: str, *, payload=None, step_id: str | None = None) -> AgentEvent:
    return AgentEvent(
        type=t,
        timestamp="2026-03-31T00:00:00Z",
        run_id="r1",
        turn_id="t1",
        step_id=step_id,
        payload=payload or {},
    )


def test_replay_summary_tracks_requested_and_finished_tool_calls() -> None:
    events = [
        _ev("run_started"),
        _ev("tool_call_requested", payload={"call_id": "c1", "name": "file_write", "arguments": {"path": "a.txt"}}),
        _ev(
            "tool_call_finished",
            payload={"call_id": "c1", "tool": "file_write", "result": {"ok": True, "data": {"written": True}}},
        ),
        _ev("run_completed", payload={"final_output": "done"}),
    ]

    _state, summary = build_resume_replay_summary(events=events)
    host_state = build_host_resume_state(events=events)

    assert summary.tool_calls.requested_count == 1
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


def test_replay_summary_preserves_pending_call_ids_and_matches_node_report() -> None:
    events = [
        _ev("run_started"),
        _ev("tool_call_requested", step_id="s1", payload={"call_id": "c1", "name": "file_write", "arguments": {}}),
        _ev(
            "tool_call_requested",
            step_id="s2",
            payload={"call_id": "c2", "name": "shell_exec", "arguments": {"argv": ["echo", "hi"]}},
        ),
        _ev("tool_call_finished", payload={"call_id": "c1", "tool": "file_write", "result": {"ok": True, "data": {}}}),
        _ev("run_cancelled", payload={"message": "waiting", "wal_locator": "wal.jsonl"}),
    ]

    report = NodeReportBuilder().build(events=events)
    _state, summary = build_resume_replay_summary(events=events)
    host_state = build_host_resume_state(events=events)

    assert summary.tool_calls.requested_count == 2
    assert summary.tool_calls.finished_count == 1
    assert summary.tool_calls.pending_count == 1
    assert summary.tool_calls.latest_pending_call_ids == ["c2"]
    assert summary.tool_calls.latest_tool_calls == [
        {"call_id": "c1", "name": "file_write", "step_id": "s1", "status": "finished"},
        {"call_id": "c2", "name": "shell_exec", "step_id": "s2", "status": "pending"},
    ]
    assert host_state.tool_calls == summary.tool_calls
    unresolved = {tc.call_id for tc in report.tool_calls if not tc.ok and tc.error_kind is None}
    assert set(summary.tool_calls.latest_pending_call_ids) == unresolved


def test_replay_summary_keeps_approval_call_without_payload_leak() -> None:
    events = [
        _ev("run_started"),
        _ev(
            "tool_call_requested",
            step_id="s1",
            payload={"call_id": "c1", "name": "apply_patch", "arguments": {"input": "SECRET_PATCH"}},
        ),
        _ev("approval_requested", step_id="s1", payload={"tool": "apply_patch", "approval_key": "k1"}),
        _ev("run_cancelled", payload={"message": "waiting", "wal_locator": "wal.jsonl"}),
    ]

    _state, summary = build_resume_replay_summary(events=events)

    assert summary.tool_calls.pending_count == 1
    assert summary.tool_calls.latest_pending_call_ids == ["c1"]
    assert summary.tool_calls.latest_tool_calls == [
        {"call_id": "c1", "name": "apply_patch", "step_id": "s1", "status": "pending"}
    ]
    assert "SECRET_PATCH" not in summary.model_dump_json()


def test_replay_summary_best_effort_handles_finish_without_request() -> None:
    events = [
        _ev("run_started"),
        _ev("tool_call_finished", payload={"call_id": "cx", "tool": "shell_exec", "result": {"ok": False}}),
        _ev("run_completed", payload={"final_output": "done"}),
    ]

    _state, summary = build_resume_replay_summary(events=events)

    assert summary.tool_calls.requested_count == 0
    assert summary.tool_calls.finished_count == 1
    assert summary.tool_calls.pending_count == 0
    assert summary.tool_calls.latest_pending_call_ids == []
    assert summary.tool_calls.latest_tool_calls == [
        {"call_id": "cx", "name": "shell_exec", "step_id": None, "status": "finished"}
    ]
