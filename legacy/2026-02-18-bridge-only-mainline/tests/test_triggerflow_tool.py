from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from agent_sdk.core.contracts import AgentEvent
from agent_sdk.tools.protocol import HumanIOProvider, ToolCall
from agent_sdk.tools.registry import ToolExecutionContext, ToolRegistry

from agently_skills_runtime.adapters.triggerflow_tool import TriggerFlowRunner, TriggerFlowToolDeps, build_triggerflow_run_flow_tool


@dataclass
class _FakeRunner(TriggerFlowRunner):
    called: int = 0
    last: Optional[Dict[str, Any]] = None

    def run_flow(
        self,
        *,
        flow_name: str,
        input: Any = None,
        timeout_sec: Optional[float] = None,
        wait_for_result: bool = True,
    ) -> Any:
        self.called += 1
        self.last = {
            "flow_name": flow_name,
            "input": input,
            "timeout_sec": timeout_sec,
            "wait_for_result": wait_for_result,
        }
        return {"ok": True, "flow": flow_name}


@dataclass
class _FakeHumanIO(HumanIOProvider):
    answer: str
    last_question: Optional[str] = None

    def request_human_input(
        self,
        *,
        call_id: str,
        question: str,
        choices: Optional[list[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        timeout_ms: Optional[int] = None,
    ) -> str:
        self.last_question = question
        return self.answer


def _collecting_ctx(*, events: List[AgentEvent], human_io: Optional[HumanIOProvider]) -> ToolExecutionContext:
    return ToolExecutionContext(
        workspace_root=Path.cwd(),
        run_id="r1",
        wal=None,
        executor=None,
        human_io=human_io,
        env=None,
        cancel_checker=None,
        redaction_values=None,
        emit_tool_events=True,
        event_sink=events.append,
        skills_manager=None,
        exec_sessions=None,
        web_search_provider=None,
        collab_manager=None,
    )


def test_triggerflow_tool_schema_is_strict():
    runner = _FakeRunner()
    spec, _handler = build_triggerflow_run_flow_tool(deps=TriggerFlowToolDeps(runner=runner))
    assert spec.name == "triggerflow_run_flow"
    assert spec.requires_approval is True
    assert spec.parameters.get("additionalProperties") is False
    assert "flow_name" in (spec.parameters.get("required") or [])


def test_triggerflow_tool_denies_when_human_io_missing_and_emits_approval_events():
    runner = _FakeRunner()
    spec, handler = build_triggerflow_run_flow_tool(deps=TriggerFlowToolDeps(runner=runner))

    emitted: List[AgentEvent] = []
    registry = ToolRegistry(ctx=_collecting_ctx(events=emitted, human_io=None))
    registry.register(spec, handler)

    result = registry.dispatch(ToolCall(call_id="c1", name="triggerflow_run_flow", args={"flow_name": "flowA"}))
    assert result.ok is False
    assert result.error_kind == "permission"
    assert runner.called == 0

    # tool_call_* 事件由 ToolRegistry 写入；approval_* 事件由 handler 写入
    types = [e.type for e in emitted]
    assert "tool_call_requested" in types
    assert "tool_call_started" in types
    assert "approval_requested" in types
    assert "approval_decided" in types
    assert "tool_call_finished" in types


def test_triggerflow_tool_runs_after_human_approval():
    runner = _FakeRunner()
    spec, handler = build_triggerflow_run_flow_tool(deps=TriggerFlowToolDeps(runner=runner))

    emitted: List[AgentEvent] = []
    human_io = _FakeHumanIO(answer="approve")
    registry = ToolRegistry(ctx=_collecting_ctx(events=emitted, human_io=human_io))
    registry.register(spec, handler)

    result = registry.dispatch(
        ToolCall(
            call_id="c1",
            name="triggerflow_run_flow",
            args={"flow_name": "flowA", "input": {"x": 1}, "timeout_sec": 1.5, "wait_for_result": True},
        )
    )
    assert result.ok is True
    assert runner.called == 1
    assert runner.last and runner.last["flow_name"] == "flowA"
    assert runner.last and runner.last["input"] == {"x": 1}
    assert human_io.last_question and "flowA" in human_io.last_question
