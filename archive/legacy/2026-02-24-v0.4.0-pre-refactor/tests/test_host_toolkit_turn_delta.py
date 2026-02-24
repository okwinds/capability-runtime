from __future__ import annotations

from agently_skills_runtime.host_toolkit.turn_delta import TurnDelta, TruncatingTurnDeltaRedactor
from agently_skills_runtime.types import NodeReportV2


def test_turn_delta_can_represent_data_and_control_and_events_pointer():
    report = NodeReportV2(
        status="success",
        reason=None,
        completion_reason="run_completed",
        engine={"name": "skills-runtime-sdk-python", "module": "agent_sdk", "version": "0"},
        bridge={"name": "agently-skills-runtime", "version": "0"},
        run_id="r1",
        turn_id="t1",
        events_path="wal.jsonl",
        activated_skills=[],
        tool_calls=[],
        artifacts=[],
        meta={},
    )
    td = TurnDelta(
        session_id="s1",
        host_turn_id="t_host_1",
        run_id="r1",
        user_input="u",
        final_output="a",
        node_report=report,
        events_path="wal.jsonl",
    )
    assert td.final_output == "a"
    assert td.node_report.run_id == "r1"
    assert td.events_path == "wal.jsonl"


def test_turn_delta_redactor_truncates_user_and_assistant_text_only():
    report = NodeReportV2(
        status="success",
        reason=None,
        completion_reason="run_completed",
        engine={"name": "skills-runtime-sdk-python", "module": "agent_sdk", "version": "0"},
        bridge={"name": "agently-skills-runtime", "version": "0"},
        run_id="r1",
        turn_id="t1",
        events_path="wal.jsonl",
        activated_skills=[],
        tool_calls=[],
        artifacts=[],
        meta={"k": "v"},
    )
    td = TurnDelta(
        user_input="x" * 10,
        final_output="y" * 10,
        node_report=report,
        events_path="wal.jsonl",
    )
    out = td.redacted(redactor=TruncatingTurnDeltaRedactor(max_chars=5))
    assert out.user_input == "xx..."
    assert out.final_output == "yy..."
    assert out.node_report.meta == {"k": "v"}
