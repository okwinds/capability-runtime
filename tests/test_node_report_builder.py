import pytest

from skills_runtime.core.contracts import AgentEvent

from capability_runtime.reporting.node_report import NodeReportBuilder


def _ev(t, *, run_id="r1", turn_id="t1", payload=None):
    return AgentEvent(type=t, timestamp="2026-02-10T00:00:00Z", run_id=run_id, turn_id=turn_id, payload=payload or {})


def _ev_step(t, *, run_id="r1", turn_id="t1", step_id="s1", payload=None):
    return AgentEvent(
        type=t, timestamp="2026-02-10T00:00:00Z", run_id=run_id, turn_id=turn_id, step_id=step_id, payload=payload or {}
    )


def test_report_success_from_run_completed():
    events = [
        _ev("run_started", payload={}),
        _ev("run_completed", payload={"final_output": "ok", "wal_locator": "wal.jsonl"}),
    ]
    rep = NodeReportBuilder().build(events=events)
    assert rep.schema_id == "capability-runtime.node_report.v1"
    assert rep.status == "success"
    assert rep.engine.get("name") == "skills-runtime-sdk-python"
    assert rep.events_path == "wal.jsonl"
    assert rep.completion_reason == "run_completed"


def test_report_collects_activated_skills_unique_and_ordered():
    events = [
        _ev("run_started"),
        _ev("skill_injected", payload={"skill_name": "a"}),
        _ev("skill_injected", payload={"skill_name": "b"}),
        _ev("skill_injected", payload={"skill_name": "a"}),
        _ev("run_completed", payload={"final_output": "ok", "wal_locator": "wal.jsonl"}),
    ]
    rep = NodeReportBuilder().build(events=events)
    assert rep.activated_skills == ["a", "b"]


def test_report_aggregates_llm_usage_summary() -> None:
    events = [
        _ev("run_started"),
        _ev("llm_usage", payload={"model": "gpt-4.1-mini", "input_tokens": 11, "output_tokens": 7, "total_tokens": 18}),
        _ev("llm_usage", payload={"model": "gpt-4.1-mini", "prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}),
        _ev("run_completed", payload={"final_output": "ok", "wal_locator": "wal.jsonl"}),
    ]
    rep = NodeReportBuilder().build(events=events)
    assert rep.usage is not None
    assert rep.usage.model == "gpt-4.1-mini"
    assert rep.usage.input_tokens == 13
    assert rep.usage.output_tokens == 10
    assert rep.usage.total_tokens == 23


def test_report_collects_artifacts_from_run_completed_payload():
    events = [
        _ev("run_started"),
        _ev(
            "run_completed",
            payload={
                "final_output": "ok",
                "wal_locator": "wal.jsonl",
                "artifacts": ["a.txt", "", "b.txt", 123, None],
            },
        ),
    ]
    rep = NodeReportBuilder().build(events=events)
    assert rep.artifacts == ["a.txt", "b.txt"]


def test_report_collects_artifacts_from_artifact_path_events_and_dedupes():
    events = [
        _ev("run_started"),
        _ev("context_compacted", payload={"artifact_path": "handoff-1.md"}),
        _ev("compaction_finished", payload={"artifact_path": "handoff-1.md"}),
        _ev(
            "run_completed",
            payload={"final_output": "ok", "wal_locator": "wal.jsonl", "artifacts": ["handoff-1.md", "handoff-2.md"]},
        ),
    ]
    rep = NodeReportBuilder().build(events=events)
    assert rep.artifacts == ["handoff-1.md", "handoff-2.md"]


def test_report_aggregates_tool_call_requested_and_finished():
    events = [
        _ev("run_started"),
        _ev("tool_call_requested", payload={"call_id": "c1", "name": "shell_exec", "arguments": {}}),
        _ev(
            "tool_call_finished",
            payload={"call_id": "c1", "tool": "shell_exec", "result": {"ok": True, "data": {"x": 1}}},
        ),
        _ev("run_completed", payload={"final_output": "ok", "wal_locator": "wal.jsonl"}),
    ]
    rep = NodeReportBuilder().build(events=events)
    assert len(rep.tool_calls) == 1
    assert rep.tool_calls[0].call_id == "c1"
    assert rep.tool_calls[0].ok is True
    assert rep.tool_calls[0].data == {"x": 1}


def test_report_marks_requires_approval_when_approval_requested():
    events = [
        _ev("run_started"),
        _ev_step("tool_call_requested", step_id="s1", payload={"call_id": "c1", "name": "shell_exec", "arguments": {}}),
        _ev_step("approval_requested", step_id="s1", payload={"tool": "shell_exec", "approval_key": "k1"}),
        _ev("run_cancelled", payload={"message": "waiting", "wal_locator": "wal.jsonl"}),
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
        _ev_step("tool_call_requested", step_id="s1", payload={"call_id": "c1", "name": "shell_exec", "arguments": {}}),
        _ev_step("approval_requested", step_id="s1", payload={"tool": "shell_exec", "approval_key": "k1"}),
        _ev_step("approval_decided", step_id="s1", payload={"decision": "approved", "reason": "ok"}),
        _ev("run_completed", payload={"final_output": "ok", "wal_locator": "wal.jsonl"}),
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
        _ev_step("approval_decided", payload={"decision": "approved", "reason": "ok"}),
        _ev_step("run_completed", payload={"final_output": "ok", "wal_locator": "wal.jsonl"}),
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
        _ev("run_failed", payload={"error_kind": error_kind, "message": "x", "wal_locator": "wal.jsonl"}),
    ]
    rep = NodeReportBuilder().build(events=events)
    assert rep.status == "failed"
    assert rep.reason == expected_reason


def test_report_cancelled_maps_to_incomplete_and_cancelled_reason():
    events = [_ev("run_started"), _ev("run_cancelled", payload={"message": "stop", "wal_locator": "wal.jsonl"})]
    rep = NodeReportBuilder().build(events=events)
    assert rep.status == "incomplete"
    assert rep.reason == "cancelled"


def test_report_waiting_human_maps_to_needs_approval_and_preserves_message():
    events = [
        _ev("run_started"),
        _ev(
            "run_waiting_human",
            payload={
                "tool": "ask_human",
                "call_id": "c1",
                "message": "需要你确认下一步",
                "error_kind": "human_required",
                "wal_locator": "wal.jsonl",
            },
        ),
    ]
    rep = NodeReportBuilder().build(events=events)
    assert rep.status == "needs_approval"
    assert rep.reason == "approval_pending"
    assert rep.completion_reason == "run_waiting_human"
    assert rep.events_path == "wal.jsonl"
    assert rep.meta["final_message"] == "需要你确认下一步"


def test_report_budget_exceeded_maps_to_incomplete_and_budget_exceeded_reason():
    events = [
        _ev("run_started"),
        _ev("run_failed", payload={"error_kind": "budget_exceeded", "message": "budget exceeded", "wal_locator": "wal.jsonl"}),
    ]
    rep = NodeReportBuilder().build(events=events)
    assert rep.status == "incomplete"
    assert rep.reason == "budget_exceeded"


def test_report_terminated_maps_to_incomplete_and_cancelled_reason():
    events = [
        _ev("run_started"),
        _ev("run_failed", payload={"error_kind": "terminated", "message": "terminated", "wal_locator": "wal.jsonl"}),
    ]
    rep = NodeReportBuilder().build(events=events)
    assert rep.status == "incomplete"
    assert rep.reason == "cancelled"


def test_report_missing_events_path_sets_meta_flag():
    events = [_ev("run_started"), _ev("run_completed", payload={"final_output": "ok"})]
    rep = NodeReportBuilder().build(events=events)
    assert rep.events_path is None
    assert rep.meta["missing_events_path"] is True


def test_report_turn_id_is_last_non_null_turn_id():
    events = [
        _ev("run_started", turn_id="t1"),
        _ev("tool_call_requested", turn_id="t2", payload={"call_id": "c1", "name": "shell_exec", "arguments": {}}),
        _ev("run_completed", turn_id="t3", payload={"final_output": "ok", "wal_locator": "wal.jsonl"}),
    ]
    rep = NodeReportBuilder().build(events=events)
    assert rep.turn_id == "t3"


def test_report_tool_calls_align_with_replay_pending_ids() -> None:
    events = [
        _ev("run_started"),
        _ev("tool_call_requested", payload={"call_id": "c1", "name": "shell_exec", "arguments": {}}),
        _ev("tool_call_requested", payload={"call_id": "c2", "name": "file_write", "arguments": {}}),
        _ev("tool_call_finished", payload={"call_id": "c1", "tool": "shell_exec", "result": {"ok": True, "data": {}}}),
        _ev("run_cancelled", payload={"message": "wait", "wal_locator": "wal.jsonl"}),
    ]

    rep = NodeReportBuilder().build(events=events)

    unresolved = {tc.call_id for tc in rep.tool_calls if not tc.ok and tc.error_kind is None}
    assert unresolved == {"c2"}


def test_report_empty_events_returns_fail_closed_node_report():
    rep = NodeReportBuilder().build(events=[])
    assert rep.status == "failed"
    assert rep.reason == "no_events"
    assert rep.completion_reason == "no_events"
    assert rep.run_id == ""
    assert rep.turn_id is None
    assert rep.events_path is None
    assert rep.engine.get("name") == "skills-runtime-sdk-python"
    assert rep.engine.get("module") == "skills_runtime"
    assert "version" in rep.engine
    assert rep.bridge.get("name") == "capability-runtime"
    assert "version" in rep.bridge


def test_report_engine_version_prefers_skills_runtime_dunder_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    回归护栏：证据链里 engine.version 应优先使用 skills_runtime.__version__。

    原因：
    - editable 安装或某些打包环境下 dist-info 版本可能漂移/滞后；
    - skills_runtime.__version__ 与运行时代码更一致，取证更可靠。
    """

    import skills_runtime
    import capability_runtime.reporting.node_report as node_report_mod

    def fake_version(_: str) -> str:
        raise AssertionError("engine.version 不应依赖 importlib.metadata.version（优先使用 skills_runtime.__version__）")

    monkeypatch.setattr(node_report_mod.importlib.metadata, "version", fake_version)

    events = [_ev("run_started"), _ev("run_completed", payload={"final_output": "ok", "wal_locator": "wal.jsonl"})]
    rep = NodeReportBuilder().build(events=events)

    assert rep.engine.get("version") == skills_runtime.__version__


def test_report_engine_version_falls_back_to_dist_name_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    回归护栏：当无法读取 skills_runtime.__version__ 时，仍需按 dist 名称顺序回退。

    历史原因某些环境可能仍以 `skills-runtime-sdk-python` 作为 dist 名，
    bridge 层应优先尝试 `skills-runtime-sdk` 并兼容回退。
    """

    import capability_runtime.reporting.node_report as node_report_mod

    calls: list[str] = []

    def fake_get_skills_runtime_version() -> None:
        return None

    def fake_version(dist_name: str) -> str:
        calls.append(dist_name)
        if dist_name == "skills-runtime-sdk":
            return "9.9.9"
        if dist_name == "capability-runtime":
            return "0.3.0"
        raise Exception("not found")

    monkeypatch.setattr(node_report_mod, "_get_skills_runtime_version", fake_get_skills_runtime_version)
    monkeypatch.setattr(node_report_mod.importlib.metadata, "version", fake_version)

    events = [_ev("run_started"), _ev("run_completed", payload={"final_output": "ok", "wal_locator": "wal.jsonl"})]
    rep = NodeReportBuilder().build(events=events)

    assert rep.engine.get("version") == "9.9.9"
    assert calls and calls[0] == "skills-runtime-sdk"
