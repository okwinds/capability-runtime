from __future__ import annotations

"""离线回归：Runtime.run_stream() 混合流语义（v1）。"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from skills_runtime.llm.chat_sse import ChatStreamEvent
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall

from capability_runtime import (
    AgentSpec,
    CapabilityKind,
    CapabilityResult,
    CapabilitySpec,
    CapabilityStatus,
    Runtime,
    RuntimeConfig,
    WorkflowSpec,
)
from capability_runtime.protocol.context import ExecutionContext
from capability_runtime.protocol.workflow import CapabilityRef, Step
from capability_runtime.types import NodeReport, NodeToolCallReport, NodeUsageReport


@pytest.mark.asyncio
async def test_run_stream_unknown_capability_emits_single_terminal_failed(tmp_path: Path) -> None:
    rt = Runtime(RuntimeConfig(mode="mock", workspace_root=tmp_path))

    items: List[Any] = []
    async for item in rt.run_stream("NOPE"):
        items.append(item)

    assert len(items) == 1
    assert isinstance(items[0], CapabilityResult)
    assert items[0].status == CapabilityStatus.FAILED
    assert "Capability not found" in str(items[0].error or "")
    assert items[0].node_report is not None
    assert items[0].node_report.reason == "capability_not_found"


@pytest.mark.asyncio
async def test_run_stream_mock_agent_may_emit_only_terminal(tmp_path: Path) -> None:
    def handler(_spec: CapabilitySpec, _input: Dict[str, Any]) -> str:
        return "ok"

    rt = Runtime(RuntimeConfig(mode="mock", workspace_root=tmp_path, mock_handler=handler))
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))

    items: List[Any] = []
    async for item in rt.run_stream("A"):
        items.append(item)

    assert len(items) == 1
    assert isinstance(items[0], CapabilityResult)
    assert items[0].status == CapabilityStatus.SUCCESS
    assert items[0].output == "ok"


@pytest.mark.asyncio
async def test_run_stream_sdk_native_terminal_is_unique_and_last(tmp_path: Path) -> None:
    backend = FakeChatBackend(
        calls=[FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="ok"), ChatStreamEvent(type="completed")])]
    )
    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=tmp_path,
            sdk_config_paths=[],
            sdk_backend=backend,
            preflight_mode="off",
        )
    )
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A", description="say ok")))

    items: List[Any] = []
    async for item in rt.run_stream("A"):
        items.append(item)

    results = [x for x in items if isinstance(x, CapabilityResult)]
    assert len(results) == 1
    assert items[-1] is results[0]
    assert results[0].output == "ok"


@pytest.mark.asyncio
async def test_run_stream_workflow_emits_workflow_events_and_terminal_last(tmp_path: Path) -> None:
    def handler(_spec: CapabilitySpec, input_dict: Dict[str, Any]) -> CapabilityResult:
        child_report = NodeReport(
            status="success",
            completion_reason="run_completed",
            run_id="child-success",
            events_path="wal://workflow-step-success",
            usage=NodeUsageReport(model="workflow-model", input_tokens=2, output_tokens=3, total_tokens=5),
            tool_calls=[NodeToolCallReport(call_id="call-success", name="lookup", ok=True)],
            artifacts=["runtime-action://workflow-artifact"],
        )
        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output={"ok": True, **input_dict},
            report=child_report,
            node_report=child_report,
        )

    rt = Runtime(RuntimeConfig(mode="mock", workspace_root=tmp_path, mock_handler=handler))
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    rt.register(
        WorkflowSpec(
            base=CapabilitySpec(id="WF", kind=CapabilityKind.WORKFLOW, name="WF"),
            steps=[Step(id="s1", capability=CapabilityRef(id="A"))],
        )
    )

    items: List[Any] = []
    async for item in rt.run_stream("WF", input={"x": 1}):
        items.append(item)

    results = [x for x in items if isinstance(x, CapabilityResult)]
    assert len(results) == 1
    assert items[-1] is results[0]
    assert results[0].node_report is not None
    assert results[0].node_report.status == "success"
    assert results[0].node_report.completion_reason == "workflow_completed"
    assert results[0].node_report.events_path == "wal://workflow-step-success"
    assert results[0].node_report.usage is not None
    assert results[0].node_report.usage.total_tokens == 5
    assert results[0].node_report.tool_calls[0].call_id == "call-success"
    assert results[0].node_report.artifacts == ["runtime-action://workflow-artifact"]
    assert results[0].node_report.meta["workflow"]["workflow_id"] == "WF"
    assert results[0].node_report.meta["workflow"]["workflow_instance_id"]
    assert results[0].node_report.meta["workflow"]["close_reason"] == "success"

    events = [x for x in items if not isinstance(x, CapabilityResult)]
    assert events, "workflow path should emit lightweight workflow.* events"
    assert all(isinstance(e, dict) and str(e.get("type") or "").startswith("workflow.") for e in events)

    run_ids = {e.get("run_id") for e in events}
    assert None not in run_ids
    assert len(run_ids) == 1

    workflow_ids = {e.get("workflow_id") for e in events}
    assert workflow_ids == {"WF"}

    instance_ids = {e.get("workflow_instance_id") for e in events}
    assert None not in instance_ids
    assert len(instance_ids) == 1

    step_started = [e for e in events if e.get("type") == "workflow.step.started"]
    assert step_started and all(e.get("step_id") for e in step_started)


@pytest.mark.asyncio
async def test_run_stream_workflow_failed_terminal_has_workflow_owned_node_report(tmp_path: Path) -> None:
    child_report = NodeReport(
        status="failed",
        reason="child_failed",
        completion_reason="child_error",
        run_id="child-run",
        meta={"step_id": "legacy-child-meta", "capability_id": "A"},
    )

    def handler(_spec: CapabilitySpec, _input: Dict[str, Any]) -> CapabilityResult:
        return CapabilityResult(
            status=CapabilityStatus.FAILED,
            error="child failed",
            error_code="CHILD_FAILED",
            report=child_report,
            node_report=child_report,
        )

    rt = Runtime(RuntimeConfig(mode="mock", workspace_root=tmp_path, mock_handler=handler))
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    rt.register(
        WorkflowSpec(
            base=CapabilitySpec(id="WF", kind=CapabilityKind.WORKFLOW, name="WF"),
            steps=[Step(id="s1", capability=CapabilityRef(id="A"))],
        )
    )

    items = [item async for item in rt.run_stream("WF")]
    terminal = next(item for item in items if isinstance(item, CapabilityResult))

    assert terminal.status == CapabilityStatus.FAILED
    assert terminal.error_code == "CHILD_FAILED"
    assert terminal.node_report is not None
    assert terminal.node_report is not child_report
    assert terminal.node_report.status == "failed"
    assert terminal.node_report.reason == "child_failed"
    assert terminal.node_report.completion_reason == "child_error"
    assert terminal.node_report.meta["workflow"]["workflow_id"] == "WF"
    assert terminal.node_report.meta["workflow"]["close_reason"] == "failed"
    assert terminal.node_report.meta["child_terminal"] == {
        "status": "failed",
        "reason": "child_failed",
        "completion_reason": "child_error",
        "run_id": "child-run",
        "error_code": "CHILD_FAILED",
    }
    assert terminal.node_report.meta["step_id"] == "legacy-child-meta"


@pytest.mark.asyncio
async def test_run_stream_workflow_pending_terminal_preserves_approval_evidence(tmp_path: Path) -> None:
    child_report = NodeReport(
        status="needs_approval",
        reason="approval_pending",
        completion_reason="needs_approval",
        run_id="child-run",
        bridge={"name": "child", "agently": {"installed_version": "4.1.3.1", "requester_strategy": "responses"}},
        tool_calls=[
            NodeToolCallReport(
                call_id="call-1",
                name="review",
                requires_approval=True,
                approval_key="approval-1",
            )
        ],
        meta={"approval_requested_at_ms": 123, "step_id": "s1"},
    )

    def handler(_spec: CapabilitySpec, _input: Dict[str, Any]) -> CapabilityResult:
        return CapabilityResult(
            status=CapabilityStatus.PENDING,
            error_code="NEEDS_APPROVAL",
            report=child_report,
            node_report=child_report,
        )

    rt = Runtime(RuntimeConfig(mode="mock", workspace_root=tmp_path, mock_handler=handler))
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    rt.register(
        WorkflowSpec(
            base=CapabilitySpec(id="WF", kind=CapabilityKind.WORKFLOW, name="WF"),
            steps=[Step(id="s1", capability=CapabilityRef(id="A"))],
        )
    )

    items = [item async for item in rt.run_stream("WF")]
    terminal = next(item for item in items if isinstance(item, CapabilityResult))

    assert terminal.status == CapabilityStatus.PENDING
    assert terminal.node_report is not None
    assert terminal.node_report.status == "needs_approval"
    assert terminal.node_report.reason == "approval_pending"
    assert terminal.node_report.completion_reason == "workflow_waiting_human"
    assert terminal.node_report.tool_calls[0].approval_key == "approval-1"
    assert terminal.node_report.meta["workflow"]["close_reason"] == "pending"
    assert terminal.node_report.meta["child_terminal"]["status"] == "needs_approval"
    assert terminal.node_report.bridge["agently"]["installed_version"] == "4.1.3.1"
    ticket = rt.build_approval_ticket(terminal, capability_id="WF")
    snapshot = rt.summarize_host_run(terminal, capability_id="WF")
    assert ticket is not None
    assert ticket.workflow_id == "WF"
    assert ticket.workflow_instance_id
    assert ticket.step_id == "s1"
    assert ticket.created_at_ms == 123
    assert snapshot.workflow_id == "WF"
    assert snapshot.workflow_instance_id == ticket.workflow_instance_id


@pytest.mark.asyncio
async def test_run_when_run_stream_emits_no_terminal_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rt = Runtime(RuntimeConfig(mode="mock", workspace_root=tmp_path))

    async def _no_terminal(capability_id: str, *, input=None, context=None):  # type: ignore[no-untyped-def]
        _ = (capability_id, input, context)
        if False:
            yield None

    monkeypatch.setattr(rt, "run_stream", _no_terminal)

    out = await rt.run("A", context=ExecutionContext(run_id="r-no-terminal"))
    assert out.status == CapabilityStatus.FAILED
    assert out.error_code == "ENGINE_ERROR"
    assert out.node_report is not None
    assert out.node_report.reason == "engine_error"
    assert out.node_report.completion_reason == "missing_terminal_result"


@pytest.mark.asyncio
async def test_execute_workflow_stream_invalid_spec_type_returns_fail_closed(tmp_path: Path) -> None:
    rt = Runtime(RuntimeConfig(mode="mock", workspace_root=tmp_path))
    invalid_spec = AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"))
    ctx = ExecutionContext(run_id="r-invalid-wf")

    items = [
        item
        async for item in rt._execute_workflow_stream(  # type: ignore[arg-type]
            spec=invalid_spec,
            input={},
            context=ctx,
        )
    ]

    assert len(items) == 1
    terminal = items[0]
    assert isinstance(terminal, CapabilityResult)
    assert terminal.status == CapabilityStatus.FAILED
    assert terminal.error_code == "INVALID_WORKFLOW_SPEC"
    assert terminal.node_report is not None
    assert terminal.node_report.reason == "invalid_spec"


@pytest.mark.asyncio
async def test_execute_agent_stream_invalid_spec_type_returns_fail_closed(tmp_path: Path) -> None:
    rt = Runtime(RuntimeConfig(mode="mock", workspace_root=tmp_path))
    invalid_spec = WorkflowSpec(
        base=CapabilitySpec(id="WF-BAD", kind=CapabilityKind.WORKFLOW, name="WF-BAD"),
        steps=[],
    )
    ctx = ExecutionContext(run_id="r-invalid-agent")

    items = [
        item
        async for item in rt._execute_agent_stream(  # type: ignore[arg-type]
            spec=invalid_spec,
            input={},
            context=ctx,
        )
    ]

    assert len(items) == 1
    terminal = items[0]
    assert isinstance(terminal, CapabilityResult)
    assert terminal.status == CapabilityStatus.FAILED
    assert terminal.error_code == "INVALID_AGENT_SPEC"
    assert terminal.node_report is not None
    assert terminal.node_report.reason == "invalid_spec"


@pytest.mark.asyncio
async def test_execute_recursion_limit_returns_fail_closed_report(tmp_path: Path) -> None:
    rt = Runtime(RuntimeConfig(mode="mock", workspace_root=tmp_path))
    spec = AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"))
    ctx = ExecutionContext(run_id="r-rec-limit", max_depth=0)

    out = await rt._execute(spec=spec, input={}, context=ctx)  # type: ignore[attr-defined]
    assert out.status == CapabilityStatus.FAILED
    assert out.error_code == "RECURSION_LIMIT"
    assert out.node_report is not None
    assert out.node_report.reason == "recursion_limit"
