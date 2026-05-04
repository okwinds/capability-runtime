from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from skills_runtime.core.contracts import AgentEvent

from capability_runtime.config import RuntimeConfig
from capability_runtime.protocol.agent import AgentIOSchema, AgentSpec
from capability_runtime.protocol.capability import CapabilityKind, CapabilityResult, CapabilitySpec, CapabilityStatus
from capability_runtime.protocol.context import ExecutionContext
from capability_runtime.runtime import Runtime
from capability_runtime.types import NodeReport


class _FakeAgent:
    """离线 fake SDK Agent：记录最终 task 并回放事件流。"""

    def __init__(self, *, events: List[AgentEvent]) -> None:
        self._events = list(events)
        self.last_task: str | None = None

    async def run_stream_async(
        self,
        task: str,
        *,
        run_id: Optional[str] = None,
        initial_history: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[AgentEvent]:
        """记录 task 并回放固定事件。"""

        _ = run_id
        _ = initial_history
        self.last_task = task
        for ev in self._events:
            yield ev


@pytest.mark.asyncio
async def test_run_prompt_control_takes_precedence_over_input_runtime_prompt(monkeypatch, tmp_path: Path) -> None:
    """显式 prompt_control 必须优先于业务 input 中的兼容 `_runtime_prompt`。"""

    fake_agent = _FakeAgent(
        events=[
            AgentEvent(type="run_started", timestamp="2026-05-04T00:00:00Z", run_id="r1", payload={}),
            AgentEvent(
                type="run_completed",
                timestamp="2026-05-04T00:00:01Z",
                run_id="r1",
                payload={"final_output": "ok"},
            ),
        ]
    )
    monkeypatch.setattr("skills_runtime.core.agent.Agent", lambda **_: fake_agent)

    rt = Runtime(RuntimeConfig(mode="sdk_native", workspace_root=tmp_path, preflight_mode="off"))
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))

    out = await rt.run(
        "A",
        input={
            "_runtime_prompt": {
                "mode": "direct_task_text",
                "task_text": "INPUT CONTROL SHOULD NOT WIN",
            },
            "topic": "demo",
        },
        prompt_control={
            "mode": "direct_task_text",
            "task_text": "EXPLICIT CONTROL WINS",
            "trace": {"prompt_hash": "sha256:" + "e" * 64},
        },
        context=ExecutionContext(run_id="r1"),
    )

    assert out.status == CapabilityStatus.SUCCESS
    assert fake_agent.last_task == "EXPLICIT CONTROL WINS"
    assert out.node_report is not None
    assert out.node_report.meta["prompt_hash"] == "sha256:" + "e" * 64


@pytest.mark.asyncio
async def test_run_stream_sets_duration_on_replaced_terminal_without_mutating_adapter_result() -> None:
    """run_stream 填充 duration_ms 时必须返回新对象，不能修改 adapter 产出的原始 result。"""

    original = CapabilityResult(
        status=CapabilityStatus.SUCCESS,
        output={"ok": True},
        artifacts=["a.txt"],
        metadata={"nested": {"keep": True}},
    )

    def handler(_spec: AgentSpec, _input: Dict[str, Any], _ctx: ExecutionContext) -> CapabilityResult:
        return original

    rt = Runtime(RuntimeConfig(mode="mock", mock_handler=handler))
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))

    items = [item async for item in rt.run_stream("A", context=ExecutionContext(run_id="r-duration"))]
    terminal = next(item for item in items if isinstance(item, CapabilityResult))

    assert terminal is not original
    assert terminal.duration_ms is not None
    assert terminal.artifacts is not original.artifacts
    assert terminal.metadata is not original.metadata
    assert terminal.metadata["nested"] is not original.metadata["nested"]
    assert original.duration_ms is None
    terminal.artifacts.append("b.txt")
    terminal.metadata["new"] = True
    terminal.metadata["nested"]["keep"] = False
    assert original.artifacts == ["a.txt"]
    assert "new" not in original.metadata
    assert original.metadata["nested"]["keep"] is True


@pytest.mark.asyncio
async def test_run_structured_does_not_mutate_original_terminal_result(monkeypatch) -> None:
    """run_structured 结构化收口必须返回新 result，不污染 run() 返回的原始 terminal。"""

    original_report = NodeReport(
        status="success",
        reason=None,
        completion_reason="completed",
        run_id="r-structured",
        events_path="wal.jsonl",
        meta={},
    )
    original = CapabilityResult(
        status=CapabilityStatus.SUCCESS,
        output='{"title":"A","summary":"B"}',
        report=original_report,
        node_report=original_report,
        metadata={"keep": "yes"},
    )

    rt = Runtime(RuntimeConfig(mode="mock"))
    rt.register(
        AgentSpec(
            base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
            output_schema=AgentIOSchema(fields={"title": "str", "summary": "str"}, required=["title"]),
        )
    )

    async def fake_run(*args: Any, **kwargs: Any) -> CapabilityResult:
        """替代 Runtime.run，返回可检测是否被污染的原始 terminal。"""

        _ = args
        _ = kwargs
        return original

    monkeypatch.setattr(rt, "run", fake_run)

    out = await rt.run_structured("A", context=ExecutionContext(run_id="r-structured"))

    assert out is not original
    assert out.status == CapabilityStatus.SUCCESS
    assert out.output == {"title": "A", "summary": "B"}
    assert out.metadata["raw_output"] == '{"title":"A","summary":"B"}'
    assert original.status == CapabilityStatus.SUCCESS
    assert original.output == '{"title":"A","summary":"B"}'
    assert original.error is None
    assert original.error_code is None
    assert "raw_output" not in original.metadata

    out.metadata["keep"] = "changed"
    assert original.metadata["keep"] == "yes"


@pytest.mark.asyncio
async def test_run_structured_syncs_separate_report_and_node_report_without_mutating_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """report 与 node_report 分离时，结构化收口后的两个报告副本必须同步状态与摘要。"""

    original_report = NodeReport(
        status="success",
        reason=None,
        completion_reason="completed",
        run_id="r-report",
        events_path="report.jsonl",
        meta={},
    )
    original_node_report = NodeReport(
        status="success",
        reason=None,
        completion_reason="completed",
        run_id="r-node-report",
        events_path="node-report.jsonl",
        meta={},
    )
    original = CapabilityResult(
        status=CapabilityStatus.SUCCESS,
        output='{"title":"A"}',
        report=original_report,
        node_report=original_node_report,
    )

    rt = Runtime(RuntimeConfig(mode="mock"))
    rt.register(
        AgentSpec(
            base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
            output_schema=AgentIOSchema(fields={"title": "str", "summary": "str"}, required=["summary"]),
        )
    )

    async def fake_run(*args: Any, **kwargs: Any) -> CapabilityResult:
        """替代 Runtime.run，返回 report/node_report 分离的 terminal。"""

        _ = args
        _ = kwargs
        return original

    monkeypatch.setattr(rt, "run", fake_run)

    out = await rt.run_structured("A", context=ExecutionContext(run_id="r-report"))

    assert out.status == CapabilityStatus.FAILED
    assert out.report is not original_report
    assert out.node_report is not original_node_report
    assert isinstance(out.report, NodeReport)
    assert out.report.status == "failed"
    assert out.report.reason == "structured_output_error"
    assert out.report.meta["structured_output"]["ok"] is False
    assert out.node_report is not None
    assert out.node_report.status == "failed"
    assert out.node_report.reason == "structured_output_error"
    assert out.node_report.meta["structured_output"]["ok"] is False
    assert original_report.status == "success"
    assert original_node_report.status == "success"


@pytest.mark.asyncio
async def test_run_structured_stream_does_not_mutate_original_terminal_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_structured_stream 结构化 terminal 事件不能污染 run_stream 原始 terminal。"""

    original_report = NodeReport(
        status="success",
        reason=None,
        completion_reason="completed",
        run_id="r-stream",
        events_path="stream.jsonl",
        meta={},
    )
    original = CapabilityResult(
        status=CapabilityStatus.SUCCESS,
        output='{"title":"A","summary":"B"}',
        report=original_report,
        node_report=original_report,
        metadata={},
    )

    rt = Runtime(RuntimeConfig(mode="mock"))
    rt.register(
        AgentSpec(
            base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
            output_schema=AgentIOSchema(fields={"title": "str", "summary": "str"}, required=["summary"]),
        )
    )

    async def fake_run_stream(*args: Any, **kwargs: Any) -> AsyncIterator[CapabilityResult]:
        """替代 Runtime.run_stream，直接产出原始 terminal。"""

        _ = args
        _ = kwargs
        yield original

    monkeypatch.setattr(rt, "run_stream", fake_run_stream)

    events = [
        ev
        async for ev in rt.run_structured_stream("A", context=ExecutionContext(run_id="r-stream"))
    ]
    terminal = next(ev for ev in events if ev.type == "terminal")

    assert terminal.status == "success"
    assert terminal.output == {"title": "A", "summary": "B"}
    assert terminal.raw_output == '{"title":"A","summary":"B"}'
    assert original.output == '{"title":"A","summary":"B"}'
    assert original.error is None
    assert "raw_output" not in original.metadata
