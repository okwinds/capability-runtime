"""回归：自定义工具注入（RuntimeConfig.custom_tools）走上游公开扩展点。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from skills_runtime.core.contracts import AgentEvent
from skills_runtime.tools.protocol import ToolSpec

from capability_runtime.config import CustomTool, RuntimeConfig
from capability_runtime.protocol.agent import AgentSpec
from capability_runtime.protocol.capability import CapabilityKind, CapabilitySpec, CapabilityStatus
from capability_runtime.protocol.context import ExecutionContext
from capability_runtime.runtime import Runtime


class _FakeAgent:
    last_instance = None

    def __init__(self, **kwargs: Any) -> None:
        _FakeAgent.last_instance = self
        self.kwargs = kwargs
        self.registered: list[tuple[str, bool]] = []

    def register_tool(self, spec, handler, *, override: bool = False) -> None:
        _ = handler
        self.registered.append((str(getattr(spec, "name", "")), bool(override)))

    async def run_stream_async(
        self,
        task: str,
        *,
        run_id: Optional[str] = None,
        initial_history: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[AgentEvent]:
        _ = task
        _ = initial_history
        yield AgentEvent(type="run_started", timestamp="2026-02-10T00:00:00Z", run_id=run_id or "r1", payload={})
        yield AgentEvent(
            type="run_completed",
            timestamp="2026-02-10T00:00:01Z",
            run_id=run_id or "r1",
            payload={"final_output": "ok", "wal_locator": "wal.jsonl"},
        )


@pytest.mark.asyncio
async def test_custom_tools_override_flag_is_propagated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("skills_runtime.core.agent.Agent", _FakeAgent)

    spec = ToolSpec(
        name="t",
        description="d",
        parameters={"type": "object", "properties": {}, "required": []},
        requires_approval=False,
    )

    def handler(call, ctx):
        _ = call
        _ = ctx
        return {"ok": True}

    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=Path("."),
            preflight_mode="off",
            custom_tools=[CustomTool(spec=spec, handler=handler, override=True)],
        )
    )
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    out = await rt.run("A", context=ExecutionContext(run_id="r1"))
    assert out.status == CapabilityStatus.SUCCESS

    agent = _FakeAgent.last_instance
    assert agent is not None
    assert ("t", True) in agent.registered
