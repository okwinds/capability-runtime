import pytest

from agent_sdk.core.contracts import AgentEvent

from agently_skills_runtime.reporting.node_report import NodeReportBuilder


def _ev(t, *, run_id="r1", turn_id="t1", payload=None):
    return AgentEvent(type=t, ts="2026-02-10T00:00:00Z", run_id=run_id, turn_id=turn_id, payload=payload or {})


def _ev_step(t, *, run_id="r1", turn_id="t1", step_id="s1", payload=None):
    return AgentEvent(
        type=t, ts="2026-02-10T00:00:00Z", run_id=run_id, turn_id=turn_id, step_id=step_id, payload=payload or {}
    )


def test_report_success_from_run_completed():
    events = [
        _ev("run_started", payload={}),
        _ev("run_completed", payload={"final_output": "ok", "events_path": "wal.jsonl"}),
    ]
    rep = NodeReportBuilder().build(events=events)
    assert rep.status == "success"
    assert rep.events_path == "wal.jsonl"
    assert rep.completion_reason == "run_completed"


def test_report_collects_activated_skills_unique_and_ordered():
    events = [
        _ev("run_started"),
        _ev("skill_injected", payload={"skill_name": "a"}),
        _ev("skill_injected", payload={"skill_name": "b"}),
        _ev("skill_injected", payload={"skill_name": "a"}),
        _ev("run_completed", payload={"final_output": "ok", "events_path": "wal.jsonl"}),
    ]
    rep = NodeReportBuilder().build(events=events)
    assert rep.activated_skills == ["a", "b"]


def test_report_aggregates_tool_call_requested_and_finished():
    events = [
        _ev("run_started"),
        _ev("tool_call_requested", payload={"call_id": "c1", "name": "shell_exec", "arguments": {}}),
        _ev(
            "tool_call_finished",
            payload={"call_id": "c1", "tool": "shell_exec", "result": {"ok": True, "data": {"x": 1}}},
        ),
        _ev("run_completed", payload={"final_output": "ok", "events_path": "wal.jsonl"}),
    ]
    rep = NodeReportBuilder().build(events=events)
    assert len(rep.tool_calls) == 1
    assert rep.tool_calls[0].call_id == "c1"
    assert rep.tool_calls[0].ok is True
    assert rep.tool_calls[0].data == {"x": 1}


def test_report_marks_requires_approval_when_approval_requested():
    events = [
        _ev("run_started"),
        _ev("tool_call_requested", payload={"call_id": "c1", "name": "shell_exec", "arguments": {}}),
        _ev("approval_requested", payload={"call_id": "c1", "tool": "shell_exec", "approval_key": "k1"}),
        _ev("run_cancelled", payload={"message": "waiting", "events_path": "wal.jsonl"}),
    ]
    rep = NodeReportBuilder().build(events=events)
    assert rep.status == "needs_approval"
    assert rep.reason == "approval_pending"
    assert rep.tool_calls[0].requires_approval is True
    assert rep.tool_calls[0].approval_key == "k1"
    assert rep.meta["approval_inference"]["requires_approval_call_ids"] == ["c1"]


def test_report_records_approval_decision_and_clears_pending():
    events = [
        _ev("run_started"),
        _ev("approval_requested", payload={"call_id": "c1", "tool": "shell_exec", "approval_key": "k1"}),
        _ev("approval_decided", payload={"call_id": "c1", "tool": "shell_exec", "decision": "approved", "reason": "ok"}),
        _ev("run_completed", payload={"final_output": "ok", "events_path": "wal.jsonl"}),
    ]
    rep = NodeReportBuilder().build(events=events)
    assert rep.status == "success"
    assert rep.tool_calls[0].approval_decision == "approved"
    assert rep.tool_calls[0].approval_reason == "ok"


def test_report_correlates_approval_events_without_call_id_via_step_id():
    """
    SDK 默认 approvals 事件形态：approval_* payload 可能不带 call_id，仅靠 step_id 与 tool_call_requested 同步关联。
    """

    events = [
        _ev_step("run_started", payload={}),
        _ev_step("tool_call_requested", payload={"call_id": "c1", "name": "shell_exec", "arguments": {}}),
        _ev_step("approval_requested", payload={"tool": "shell_exec", "approval_key": "k1"}),
        _ev_step("approval_decided", payload={"tool": "shell_exec", "decision": "approved", "reason": "ok"}),
        _ev_step("run_completed", payload={"final_output": "ok", "events_path": "wal.jsonl"}),
    ]
    rep = NodeReportBuilder().build(events=events)
    assert rep.status == "success"
    assert len(rep.tool_calls) == 1
    assert rep.tool_calls[0].call_id == "c1"
    assert rep.tool_calls[0].requires_approval is True
    assert rep.tool_calls[0].approval_key == "k1"
    assert rep.tool_calls[0].approval_decision == "approved"
    assert rep.tool_calls[0].approval_reason == "ok"
    assert rep.meta["approval_inference"]["requires_approval_call_ids"] == ["c1"]


@pytest.mark.parametrize(
    "error_kind,expected_reason",
    [
        ("network_error", "llm_error"),
        ("auth_error", "llm_error"),
        ("rate_limited", "llm_error"),
        ("validation", "skill_config_error"),
        ("not_found", "skill_config_error"),
        ("config_error", "skill_config_error"),
        ("permission", "tool_error"),
    ],
)
def test_report_reason_mapping_for_run_failed(error_kind, expected_reason):
    events = [
        _ev("run_started"),
        _ev("run_failed", payload={"error_kind": error_kind, "message": "x", "events_path": "wal.jsonl"}),
    ]
    rep = NodeReportBuilder().build(events=events)
    assert rep.status == "failed"
    assert rep.reason == expected_reason


def test_report_cancelled_maps_to_incomplete_and_cancelled_reason():
    events = [_ev("run_started"), _ev("run_cancelled", payload={"message": "stop", "events_path": "wal.jsonl"})]
    rep = NodeReportBuilder().build(events=events)
    assert rep.status == "incomplete"
    assert rep.reason == "cancelled"


def test_report_budget_exceeded_maps_to_incomplete_and_budget_exceeded_reason():
    events = [
        _ev("run_started"),
        _ev("run_failed", payload={"error_kind": "budget_exceeded", "message": "budget exceeded", "events_path": "wal.jsonl"}),
    ]
    rep = NodeReportBuilder().build(events=events)
    assert rep.status == "incomplete"
    assert rep.reason == "budget_exceeded"


def test_report_missing_events_path_sets_meta_flag():
    events = [_ev("run_started"), _ev("run_completed", payload={"final_output": "ok"})]
    rep = NodeReportBuilder().build(events=events)
    assert rep.events_path is None
    assert rep.meta["missing_events_path"] is True


def test_report_turn_id_is_last_non_null_turn_id():
    events = [
        _ev("run_started", turn_id="t1"),
        _ev("tool_call_requested", turn_id="t2", payload={"call_id": "c1", "name": "shell_exec", "arguments": {}}),
        _ev("run_completed", turn_id="t3", payload={"final_output": "ok", "events_path": "wal.jsonl"}),
    ]
    rep = NodeReportBuilder().build(events=events)
    assert rep.turn_id == "t3"


def test_report_raises_on_empty_events():
    with pytest.raises(ValueError, match="non-empty"):
        NodeReportBuilder().build(events=[])


def test_report_engine_version_uses_skills_runtime_sdk_dist_name_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    回归护栏：skills-runtime-sdk 的 distribution 名称是 `skills-runtime-sdk`。

    历史原因某些环境可能仍以 `skills-runtime-sdk-python` 作为 dist 名，
    bridge 层应优先尝试前者并兼容回退。
    """

    import agently_skills_runtime.reporting.node_report as node_report_mod

    calls: list[str] = []

    def fake_version(dist_name: str) -> str:
        calls.append(dist_name)
        if dist_name == "skills-runtime-sdk":
            return "9.9.9"
        if dist_name == "agently-skills-runtime":
            return "0.3.0"
        raise Exception("not found")

    monkeypatch.setattr(node_report_mod.importlib.metadata, "version", fake_version)

    events = [_ev("run_started"), _ev("run_completed", payload={"final_output": "ok", "events_path": "wal.jsonl"})]
    rep = NodeReportBuilder().build(events=events)

    assert rep.engine.get("version") == "9.9.9"
    assert "skills-runtime-sdk" in calls
