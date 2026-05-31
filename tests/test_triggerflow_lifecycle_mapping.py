from __future__ import annotations

from typing import Any, Callable

import pytest

from capability_runtime import (
    AgentSpec,
    CapabilityKind,
    CapabilityRef,
    CapabilityResult,
    CapabilitySpec,
    CapabilityStatus,
    ExecutionContext,
    Runtime,
    RuntimeConfig,
    Step,
    WorkflowRunStatus,
    WorkflowSpec,
)
from capability_runtime.ui_events.v1 import StreamLevel


def _runtime(
    handler: Callable[[AgentSpec, dict[str, Any], ExecutionContext | None], CapabilityResult] | None = None,
) -> Runtime:
    """构造 lifecycle 映射测试用离线 Runtime。"""

    if handler is None:
        handler = lambda spec, input, context=None: CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output={"handled_by": spec.base.id, "input": dict(input)},
        )
    return Runtime(
        RuntimeConfig(
            mode="mock",
            mock_handler=handler,
        )
    )


def _register_workflow(rt: Runtime) -> None:
    """注册最小 workflow，避免依赖真实 LLM 或上游 execution 对象。"""

    rt.register(AgentSpec(base=CapabilitySpec(id="agent.lifecycle", kind=CapabilityKind.AGENT, name="AgentLifecycle")))
    rt.register(
        WorkflowSpec(
            base=CapabilitySpec(id="wf.lifecycle", kind=CapabilityKind.WORKFLOW, name="Lifecycle Workflow"),
            steps=[Step(id="draft", capability=CapabilityRef(id="agent.lifecycle"))],
        )
    )


@pytest.mark.asyncio
async def test_triggerflow_lifecycle_events_are_additive_and_snapshot_safe() -> None:
    """Slice E happy path：lifecycle 摘要进入轻量事件与 WorkflowRunSnapshot。"""

    rt = _runtime()
    _register_workflow(rt)
    ctx = ExecutionContext(run_id="run-lifecycle-1")

    items = [item async for item in rt.run_workflow_observable("wf.lifecycle", input={"topic": "x"}, context=ctx)]
    workflow_events = [item for item in items if isinstance(item, dict)]
    terminal = next(item for item in items if isinstance(item, CapabilityResult))

    started = next(ev for ev in workflow_events if ev.get("type") == "workflow.started")
    finished = next(ev for ev in workflow_events if ev.get("type") == "workflow.finished")
    lifecycle_events = [ev for ev in workflow_events if ev.get("type") == "workflow.lifecycle.changed"]

    assert started["lifecycle_state"] == "open"
    assert isinstance(started["execution_id"], str) and started["execution_id"]
    assert started["state_version"] == 0
    assert finished["lifecycle_state"] == "closed"
    assert finished["close_reason"] == "success"
    assert finished["execution_id"] == started["execution_id"]
    assert finished["state_version"] > started["state_version"]
    assert lifecycle_events, "expected additive lifecycle change events"

    snapshot = rt.summarize_workflow_run(workflow_id="wf.lifecycle", items=workflow_events, terminal=terminal)
    assert snapshot.status == WorkflowRunStatus.COMPLETED
    assert snapshot.lifecycle_state == "closed"
    assert snapshot.execution_id == started["execution_id"]
    assert snapshot.close_reason == "success"
    assert snapshot.state_version == finished["state_version"]
    assert snapshot.pending_interventions == []

    dumped = repr(snapshot) + "\n".join(str(ev) for ev in workflow_events)
    assert "TriggerFlowExecution" not in dumped
    assert "flow.async_start" not in dumped


def test_summarize_workflow_items_keeps_legacy_events_compatible() -> None:
    """Slice E regression：旧 workflow 事件缺 lifecycle 字段时仍可 summarize。"""

    rt = _runtime()
    snapshot = rt.summarize_workflow_run(
        workflow_id="wf.legacy",
        items=[
            {
                "type": "workflow.started",
                "run_id": "run-legacy",
                "workflow_id": "wf.legacy",
                "workflow_instance_id": "wf-inst-legacy",
            },
            {
                "type": "workflow.finished",
                "run_id": "run-legacy",
                "workflow_id": "wf.legacy",
                "workflow_instance_id": "wf-inst-legacy",
                "status": "success",
            },
        ],
        terminal=CapabilityResult(status=CapabilityStatus.SUCCESS),
    )

    assert snapshot.status == WorkflowRunStatus.COMPLETED
    assert snapshot.lifecycle_state is None
    assert snapshot.execution_id is None
    assert snapshot.close_reason is None


@pytest.mark.asyncio
async def test_run_ui_events_and_session_project_workflow_lifecycle_additively() -> None:
    """Slice E UI：run_ui_events 与 session 入口都投影 lifecycle，且 path 不变。"""

    rt = _runtime()
    _register_workflow(rt)

    out = []
    async for ev in rt.run_ui_events("wf.lifecycle", input={}, level=StreamLevel.UI):
        out.append(ev)
        if ev.type == "run.status" and ev.data.get("status") in {"completed", "failed", "cancelled", "pending"}:
            break

    lifecycle_node_events = [
        ev for ev in out if ev.type in {"node.started", "node.phase", "node.finished"} and ev.data.get("lifecycle_state")
    ]
    assert lifecycle_node_events
    assert any(ev.data.get("close_reason") == "success" for ev in lifecycle_node_events)
    assert all(any(seg.kind == "workflow" and seg.id for seg in ev.path) for ev in lifecycle_node_events)
    allowed_phases = {"IDLE", "THINKING", "TOOL_RUNNING", "WAITING_APPROVAL", "RUNNING", "REPORTING", "DONE"}
    assert all(ev.data.get("phase") in allowed_phases for ev in out if ev.type == "node.phase")
    assert any(ev.type == "workflow.lifecycle.changed" for ev in out)

    sess = rt.start_ui_events_session("wf.lifecycle", input={}, level=StreamLevel.UI, store_max_events=10_000)
    session_out = []
    async for ev in sess.subscribe(after_id=None):
        session_out.append(ev)
        if ev.type == "run.status" and ev.data.get("status") in {"completed", "failed", "cancelled", "pending"}:
            break

    session_dump = "\n".join(str(ev.model_dump(by_alias=True)) for ev in session_out)
    assert "lifecycle_state" in session_dump
    assert "TriggerFlowExecution" not in session_dump


@pytest.mark.asyncio
async def test_triggerflow_lifecycle_failure_keeps_legacy_event_subsequence() -> None:
    """Slice E regression：失败路径中 lifecycle 只能 additive，旧事件子序列和终态保持稳定。"""

    def fail_handler(spec: AgentSpec, input: dict[str, Any], context: ExecutionContext | None = None) -> CapabilityResult:
        _ = (input, context)
        return CapabilityResult(status=CapabilityStatus.FAILED, error=f"{spec.base.id} failed", error_code="STEP_FAILED")

    rt = _runtime(fail_handler)
    _register_workflow(rt)

    items = [item async for item in rt.run_workflow_observable("wf.lifecycle", input={})]
    workflow_events = [item for item in items if isinstance(item, dict)]
    terminal = next(item for item in items if isinstance(item, CapabilityResult))
    legacy_types = [ev["type"] for ev in workflow_events if ev["type"] != "workflow.lifecycle.changed"]

    assert terminal.status == CapabilityStatus.FAILED
    assert legacy_types == [
        "workflow.started",
        "workflow.step.started",
        "workflow.step.finished",
        "workflow.finished",
    ]
    finished = workflow_events[-1]
    assert finished["type"] == "workflow.finished"
    assert finished["status"] == "failed"
    assert finished["lifecycle_state"] == "closed"
    assert finished["close_reason"] == "failed"

    snapshot = rt.summarize_workflow_run(workflow_id="wf.lifecycle", items=workflow_events, terminal=terminal)
    assert snapshot.status == WorkflowRunStatus.FAILED
    assert snapshot.lifecycle_state == "closed"
    assert snapshot.close_reason == "failed"


def test_projector_maps_workflow_intervention_unsupported_without_native_type_leak() -> None:
    """Slice E error path：intervention preview 不支持时用稳定错误码表达。"""

    from capability_runtime.ui_events.projector import RuntimeUIEventProjector

    projector = RuntimeUIEventProjector(run_id="run-intervention", level=StreamLevel.UI)
    events = projector.on_workflow_event(
        {
            "type": "workflow.intervention.unsupported",
            "run_id": "run-intervention",
            "workflow_id": "wf.lifecycle",
            "workflow_instance_id": "wf-inst",
            "execution_id": "exec-1",
            "state_version": 3,
            "intervention_mode": "planned",
            "pending_interventions": [{"id": "int-1", "target": "draft", "status": "pending"}],
            "error_code": "WORKFLOW_INTERVENTION_UNSUPPORTED",
        }
    )

    assert events
    assert any(ev.type == "workflow.intervention.unsupported" for ev in events)
    assert any(ev.type == "error" for ev in events)
    allowed_phases = {"IDLE", "THINKING", "TOOL_RUNNING", "WAITING_APPROVAL", "RUNNING", "REPORTING", "DONE"}
    assert all(ev.data.get("phase") in allowed_phases for ev in events if ev.type == "node.phase")
    dumped = "\n".join(str(ev.model_dump(by_alias=True)) for ev in events)
    assert "WORKFLOW_INTERVENTION_UNSUPPORTED" in dumped
    assert "TriggerFlowInterventionEvent" not in dumped
    assert "TriggerFlowExecution" not in dumped
