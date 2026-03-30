from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from skills_runtime.core.contracts import AgentEvent
from skills_runtime.tools.protocol import ToolSpec

class _FakeAgent:
    last_instance = None

    def __init__(
        self,
        **kwargs: Any,
    ):
        _FakeAgent.last_instance = self
        self.kwargs = kwargs
        self.registered: list[tuple[str, bool, Any]] = []

    def register_tool(self, spec, handler, *, override: bool = False, descriptor: Any = None) -> None:
        _ = handler
        self.registered.append((str(getattr(spec, "name", "")), bool(override), descriptor))

    async def run_stream_async(self, task, *, run_id=None, initial_history=None) -> AsyncIterator[AgentEvent]:
        _ = task
        _ = run_id
        _ = initial_history
        yield AgentEvent(type="run_started", timestamp="2026-02-10T00:00:00Z", run_id="r1", payload={})
        yield AgentEvent(
            type="run_completed",
            timestamp="2026-02-10T00:00:01Z",
            run_id="r1",
            payload={"final_output": "ok", "wal_locator": "wal.jsonl"},
        )


@pytest.mark.asyncio
async def test_custom_tools_are_injected_into_sdk_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    回归护栏：RuntimeConfig.custom_tools 必须在每次创建 SDK Agent 时注入（公共扩展点）。
    """

    monkeypatch.setattr("skills_runtime.core.agent.Agent", _FakeAgent)

    spec = ToolSpec(
        name="run_workflow",
        description="demo",
        parameters={"type": "object", "properties": {"workflow_id": {"type": "string"}}, "required": ["workflow_id"]},
        requires_approval=True,
    )

    def handler(call, ctx):
        _ = call
        _ = ctx
        raise RuntimeError("should not be executed in this test")

    from capability_runtime.config import CustomTool, RuntimeConfig
    from capability_runtime.protocol.agent import AgentSpec
    from capability_runtime.protocol.capability import CapabilityKind, CapabilitySpec
    from capability_runtime.protocol.context import ExecutionContext
    from capability_runtime.runtime import Runtime

    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=Path("."),
            preflight_mode="off",
            custom_tools=[CustomTool(spec=spec, handler=handler, override=False, descriptor={"policy": "safe"})],
        )
    )
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    sdk_agent = rt.create_sdk_agent()

    out = await rt.run("A", context=ExecutionContext(run_id="r1"))
    assert out.output == "ok"

    agent = _FakeAgent.last_instance
    assert agent is not None
    assert ("run_workflow", False, {"policy": "safe"}) in agent.registered
    assert getattr(sdk_agent, "_caprt_tool_registration_diagnostics") == {
        "run_workflow": {
            "descriptor_requested": True,
            "descriptor_supported": True,
            "descriptor_applied": True,
        }
    }
