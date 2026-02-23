from __future__ import annotations

from agently_skills_runtime.host_toolkit.history import HistoryAssembler
from agently_skills_runtime.host_toolkit.turn_delta import TurnDelta
from agently_skills_runtime.types import NodeReportV2


def test_history_assembler_outputs_minimal_user_assistant_messages_only():
    report = NodeReportV2(
        status="success",
        reason=None,
        completion_reason="run_completed",
        engine={"name": "skills-runtime-sdk", "module": "agent_sdk", "version": "0"},
        bridge={"name": "agently-skills-runtime", "version": "0"},
        run_id="r1",
        turn_id="t1",
        events_path="wal.jsonl",
        activated_skills=[],
        tool_calls=[],
        artifacts=[],
        meta={},
    )
    d1 = TurnDelta(user_input="u1", final_output="a1", node_report=report, events_path="wal.jsonl")
    d2 = TurnDelta(user_input="u2", final_output="a2", node_report=report, events_path="wal.jsonl")

    out = HistoryAssembler().build_initial_history(deltas=[d1, d2])

    assert out == [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
    ]

