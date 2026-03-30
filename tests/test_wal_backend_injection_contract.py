from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from skills_runtime.core.contracts import AgentEvent

from capability_runtime.config import RuntimeConfig
from capability_runtime.protocol.agent import AgentSpec
from capability_runtime.protocol.capability import CapabilityKind, CapabilitySpec, CapabilityStatus
from capability_runtime.protocol.context import ExecutionContext
from capability_runtime.runtime import Runtime


class _FakeWalBackend:
    def read_events(self, locator: str):
        _ = locator
        return []


class _FakeAgent:
    last_instance = None

    def __init__(self, **kwargs: Any) -> None:
        _FakeAgent.last_instance = self
        self.kwargs = kwargs

    def register_tool(self, spec, handler, *, override: bool = False) -> None:
        _ = (spec, handler, override)

    async def run_stream_async(
        self,
        task: str,
        *,
        run_id: Optional[str] = None,
        initial_history: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[AgentEvent]:
        _ = (task, initial_history)
        yield AgentEvent(type="run_started", timestamp="2026-03-31T00:00:00Z", run_id=run_id or "r1", payload={})
        yield AgentEvent(
            type="run_completed",
            timestamp="2026-03-31T00:00:01Z",
            run_id=run_id or "r1",
            payload={"final_output": "ok", "wal_locator": "wal://run/123"},
        )


@pytest.mark.asyncio
async def test_runtime_wal_backend_is_forwarded_to_sdk_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("skills_runtime.core.agent.Agent", _FakeAgent)
    wal_backend = _FakeWalBackend()

    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=Path("."),
            preflight_mode="off",
            wal_backend=wal_backend,
        )
    )
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))

    out = await rt.run("A", context=ExecutionContext(run_id="r-wal"))

    assert out.status == CapabilityStatus.SUCCESS
    agent = _FakeAgent.last_instance
    assert agent is not None
    assert agent.kwargs.get("wal_backend") is wal_backend
