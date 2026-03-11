from __future__ import annotations

"""离线回归：NodeReport v1 契约护栏（字段集合/别名/聚合边界）。"""

import pytest
from pydantic import ValidationError

from skills_runtime.core.contracts import AgentEvent

from capability_runtime.reporting.node_report import NodeReportBuilder
from capability_runtime.types import NodeReport, NodeToolCallReport, NodeUsageReport


def _ev(t: str, *, run_id: str = "r1", turn_id: str = "t1", step_id: str | None = None, payload=None) -> AgentEvent:
    return AgentEvent(
        type=t,
        timestamp="2026-02-10T00:00:00Z",
        run_id=run_id,
        turn_id=turn_id,
        step_id=step_id,
        payload=payload or {},
    )


def test_node_report_schema_alias_is_schema() -> None:
    rep = NodeReport(
        status="success",
        reason=None,
        completion_reason="run_completed",
        engine={"name": "skills-runtime-sdk-python", "module": "skills_runtime"},
        bridge={"name": "capability-runtime"},
        run_id="r1",
        turn_id=None,
        events_path=None,
        usage=None,
        activated_skills=[],
        tool_calls=[],
        artifacts=[],
        meta={},
    )
    dumped = rep.model_dump(by_alias=True)
    assert set(dumped.keys()) == {
        "schema",
        "status",
        "reason",
        "completion_reason",
        "engine",
        "bridge",
        "run_id",
        "turn_id",
        "events_path",
        "usage",
        "activated_skills",
        "tool_calls",
        "artifacts",
        "meta",
    }
    assert dumped.get("schema") == "capability-runtime.node_report.v1"
    assert "schema_id" not in dumped


def test_node_tool_call_report_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        NodeToolCallReport.model_validate(
            {
                "call_id": "c1",
                "name": "t",
                "ok": True,
                "data": {"x": 1},
                "unexpected": 123,
            }
        )

    ok = NodeToolCallReport.model_validate({"call_id": "c1", "name": "t"})
    assert set(ok.model_dump().keys()) == {
        "call_id",
        "name",
        "requires_approval",
        "approval_key",
        "approval_decision",
        "approval_reason",
        "ok",
        "error_kind",
        "data",
    }


def test_node_usage_report_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        NodeUsageReport.model_validate({"model": "m", "total_tokens": 1, "unexpected": True})


def test_events_path_must_come_from_terminal_run_event() -> None:
    # 非终态事件携带 wal_locator/events_path 不应被采纳；只有 run_* 终态事件可提供 locator。
    events = [
        _ev("run_started"),
        _ev("tool_call_requested", payload={"call_id": "c1", "name": "x", "wal_locator": "NOT_ALLOWED.jsonl"}),
        _ev("run_completed", payload={"final_output": "ok"}),  # 缺失 locator
    ]
    rep = NodeReportBuilder().build(events=events)
    assert rep.events_path is None
    assert rep.meta.get("missing_events_path") is True


def test_needs_approval_has_higher_priority_than_run_failed() -> None:
    events = [
        _ev("run_started", step_id="s1"),
        _ev("tool_call_requested", step_id="s1", payload={"call_id": "c1", "name": "shell_exec", "arguments": {}}),
        _ev("approval_requested", step_id="s1", payload={"tool": "shell_exec", "approval_key": "k1"}),
        _ev("run_failed", payload={"error_kind": "validation", "message": "x", "wal_locator": "wal.jsonl"}),
    ]
    rep = NodeReportBuilder().build(events=events)
    assert rep.status == "needs_approval"
    assert rep.reason == "approval_pending"
