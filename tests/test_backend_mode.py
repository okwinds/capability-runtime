from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from agent_sdk.core.contracts import AgentEvent

from agently_skills_runtime.config import RuntimeConfig
from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.protocol.capability import CapabilityKind, CapabilitySpec
from agently_skills_runtime.protocol.context import ExecutionContext
from agently_skills_runtime.runtime import Runtime


class _FakeAgent:
    """最小 Fake SDK Agent：记录 backend 并回放固定事件。"""

    last_instance = None

    def __init__(self, **kwargs: Any) -> None:
        _FakeAgent.last_instance = self
        self.kwargs = kwargs

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


def test_bridge_mode_requires_agently_agent() -> None:
    with pytest.raises(ValueError, match="agently_agent"):
        Runtime(RuntimeConfig(mode="bridge", agently_agent=None))  # type: ignore[arg-type]


def test_bridge_mode_calls_requester_factory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    called: Dict[str, Any] = {"ok": False}

    def _factory(*, agently_agent: Any):
        _ = agently_agent
        called["ok"] = True

        def _rf():
            raise RuntimeError("not used in this test")

        return _rf

    class _FakeAgentlyChatBackend:
        def __init__(self, *, config: Any) -> None:
            self.config = config

    import agently_skills_runtime.adapters.agently_backend as ab

    monkeypatch.setattr(ab, "build_openai_compatible_requester_factory", _factory)
    monkeypatch.setattr(ab, "AgentlyChatBackend", _FakeAgentlyChatBackend)
    monkeypatch.setattr("agent_sdk.core.agent.Agent", _FakeAgent)

    rt = Runtime(RuntimeConfig(mode="bridge", workspace_root=tmp_path, agently_agent=object(), preflight_mode="off"))
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    assert called["ok"] is True


@pytest.mark.asyncio
async def test_sdk_native_mode_does_not_call_requester_factory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import agently_skills_runtime.adapters.agently_backend as ab

    monkeypatch.setattr(
        ab,
        "build_openai_compatible_requester_factory",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not call requester factory in sdk_native")),
    )
    monkeypatch.setattr("agent_sdk.core.agent.Agent", _FakeAgent)

    rt = Runtime(RuntimeConfig(mode="sdk_native", workspace_root=tmp_path, preflight_mode="off"))
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    out = await rt.run("A", context=ExecutionContext(run_id="r1"))
    assert out.output == "ok"


@pytest.mark.asyncio
async def test_sdk_native_mode_passes_openai_backend_to_agent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("agent_sdk.core.agent.Agent", _FakeAgent)

    rt = Runtime(RuntimeConfig(mode="sdk_native", workspace_root=tmp_path, preflight_mode="off"))
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    _ = await rt.run("A", context=ExecutionContext(run_id="r1"))

    agent = _FakeAgent.last_instance
    assert agent is not None
    backend = agent.kwargs.get("backend")
    assert backend is not None
    assert backend.__class__.__name__ == "OpenAIChatCompletionsBackend"
