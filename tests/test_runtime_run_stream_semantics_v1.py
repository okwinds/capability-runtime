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
from capability_runtime.protocol.workflow import CapabilityRef, Step


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
    def handler(_spec: CapabilitySpec, input_dict: Dict[str, Any]) -> Dict[str, Any]:
        return {"ok": True, **input_dict}

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
