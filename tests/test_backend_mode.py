from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from skills_runtime.core.contracts import AgentEvent

from capability_runtime.config import RuntimeConfig
from capability_runtime.protocol.agent import AgentSpec
from capability_runtime.protocol.capability import CapabilityKind, CapabilitySpec
from capability_runtime.protocol.context import ExecutionContext
from capability_runtime.runtime import Runtime


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
    with pytest.raises(ValueError, match="provider_requester_factory|agently_agent"):
        Runtime(RuntimeConfig(mode="bridge", agently_agent=None))  # type: ignore[arg-type]


def test_bridge_mode_accepts_provider_requester_factory_without_upstream_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """首选 bridge 注入面不要求下游持有底层 provider 原生 agent。"""

    called: Dict[str, Any] = {"requester_factory": None, "strategy": None}

    def _requester_factory():
        raise RuntimeError("not used in this test")

    setattr(_requester_factory, "requester_strategy", "responses")

    class _FakeProviderChatBackend:
        def __init__(self, *, config: Any) -> None:
            called["requester_factory"] = config.requester_factory
            called["strategy"] = config.requester_strategy

    import capability_runtime.adapters.agently_backend as ab

    monkeypatch.setattr(
        ab,
        "build_agently_requester_factory",
        lambda **_: (_ for _ in ()).throw(AssertionError("provider_requester_factory must bypass upstream agent")),
        raising=False,
    )
    monkeypatch.setattr(ab, "AgentlyChatBackend", _FakeProviderChatBackend)
    monkeypatch.setattr("skills_runtime.core.agent.Agent", _FakeAgent)

    rt = Runtime(
        RuntimeConfig(
            mode="bridge",
            workspace_root=tmp_path,
            provider_requester_factory=_requester_factory,
            requester_strategy="responses",
            preflight_mode="off",
        )
    )
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))

    assert called == {"requester_factory": _requester_factory, "strategy": "responses"}


def test_bridge_mode_rejects_provider_requester_factory_strategy_conflict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Requester factory metadata must not disagree with RuntimeConfig strategy."""

    def _requester_factory():
        raise RuntimeError("not used in this test")

    setattr(_requester_factory, "requester_strategy", "responses")

    class _FakeProviderChatBackend:
        def __init__(self, *, config: Any) -> None:
            self.config = config

    import capability_runtime.adapters.agently_backend as ab

    monkeypatch.setattr(ab, "AgentlyChatBackend", _FakeProviderChatBackend)
    monkeypatch.setattr("skills_runtime.core.agent.Agent", _FakeAgent)

    with pytest.raises(ValueError, match="provider_requester_factory requester_strategy conflicts"):
        Runtime(
            RuntimeConfig(
                mode="bridge",
                workspace_root=tmp_path,
                provider_requester_factory=_requester_factory,
                requester_strategy="chat_completions",
                preflight_mode="off",
            )
        )


def test_bridge_mode_default_uses_chat_completions_requester_strategy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    called: Dict[str, Any] = {"strategy": None, "agently_agent": None}

    def _factory(*, agently_agent: Any, strategy: str):
        called["strategy"] = strategy
        called["agently_agent"] = agently_agent

        def _rf():
            raise RuntimeError("not used in this test")

        return _rf

    class _FakeAgentlyChatBackend:
        def __init__(self, *, config: Any) -> None:
            self.config = config

    import capability_runtime.adapters.agently_backend as ab

    monkeypatch.setattr(
        ab,
        "build_openai_compatible_requester_factory",
        lambda **_: (_ for _ in ()).throw(AssertionError("legacy factory must be wrapped by strategy selector")),
    )
    monkeypatch.setattr(ab, "build_agently_requester_factory", _factory, raising=False)
    monkeypatch.setattr(ab, "AgentlyChatBackend", _FakeAgentlyChatBackend)
    monkeypatch.setattr("skills_runtime.core.agent.Agent", _FakeAgent)

    agently_agent = object()
    rt = Runtime(RuntimeConfig(mode="bridge", workspace_root=tmp_path, agently_agent=agently_agent, preflight_mode="off"))
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    assert called == {"strategy": "chat_completions", "agently_agent": agently_agent}


def test_bridge_mode_can_opt_into_responses_requester_strategy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    called: Dict[str, Any] = {"strategy": None}

    def _factory(*, agently_agent: Any, strategy: str):
        _ = agently_agent
        called["strategy"] = strategy

        def _rf():
            raise RuntimeError("not used in this test")

        return _rf

    class _FakeAgentlyChatBackend:
        def __init__(self, *, config: Any) -> None:
            self.config = config

    import capability_runtime.adapters.agently_backend as ab

    monkeypatch.setattr(
        ab,
        "build_openai_compatible_requester_factory",
        lambda **_: (_ for _ in ()).throw(AssertionError("legacy factory must be wrapped by strategy selector")),
    )
    monkeypatch.setattr(ab, "build_agently_requester_factory", _factory, raising=False)
    monkeypatch.setattr(ab, "AgentlyChatBackend", _FakeAgentlyChatBackend)
    monkeypatch.setattr("skills_runtime.core.agent.Agent", _FakeAgent)

    rt = Runtime(
        RuntimeConfig(
            mode="bridge",
            workspace_root=tmp_path,
            agently_agent=object(),
            requester_strategy="responses",
            preflight_mode="off",
        )
    )
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    assert called["strategy"] == "responses"


def test_bridge_mode_accepts_legacy_agently_requester_alias(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    called: Dict[str, Any] = {"strategy": None}

    def _factory(*, agently_agent: Any, strategy: str):
        _ = agently_agent
        called["strategy"] = strategy

        def _rf():
            raise RuntimeError("not used in this test")

        return _rf

    class _FakeAgentlyChatBackend:
        def __init__(self, *, config: Any) -> None:
            self.config = config

    import capability_runtime.adapters.agently_backend as ab

    monkeypatch.setattr(ab, "build_agently_requester_factory", _factory, raising=False)
    monkeypatch.setattr(ab, "AgentlyChatBackend", _FakeAgentlyChatBackend)
    monkeypatch.setattr("skills_runtime.core.agent.Agent", _FakeAgent)

    rt = Runtime(
        RuntimeConfig(
            mode="bridge",
            workspace_root=tmp_path,
            agently_agent=object(),
            agently_requester="responses",
            preflight_mode="off",
        )
    )
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    assert called["strategy"] == "responses"


def test_sdk_backend_injection_ignores_provider_requester_strategy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class _InjectedBackend:
        pass

    import capability_runtime.adapters.agently_backend as ab

    monkeypatch.setattr(
        ab,
        "build_agently_requester_factory",
        lambda **_: (_ for _ in ()).throw(AssertionError("sdk_backend must bypass Agently requester selection")),
        raising=False,
    )

    injected = _InjectedBackend()
    rt = Runtime(
        RuntimeConfig(
            mode="bridge",
            workspace_root=tmp_path,
            agently_agent=object(),
            sdk_backend=injected,  # type: ignore[arg-type]
            requester_strategy="responses",
            preflight_mode="off",
        )
    )
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    assert rt._sdk.state.backend is injected


def test_runtime_config_rejects_provider_requester_factory_without_strategy(tmp_path: Path) -> None:
    """自定义 provider_requester_factory 必须声明 runtime-owned strategy 元数据。"""

    def _requester_factory():
        raise RuntimeError("not used in this test")

    with pytest.raises(ValueError, match="provider_requester_factory must expose requester_strategy"):
        RuntimeConfig(
            mode="bridge",
            workspace_root=tmp_path,
            provider_requester_factory=_requester_factory,
        )


@pytest.mark.asyncio
async def test_sdk_native_mode_does_not_call_requester_factory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import capability_runtime.adapters.agently_backend as ab

    monkeypatch.setattr(
        ab,
        "build_openai_compatible_requester_factory",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not call requester factory in sdk_native")),
    )
    monkeypatch.setattr("skills_runtime.core.agent.Agent", _FakeAgent)

    rt = Runtime(RuntimeConfig(mode="sdk_native", workspace_root=tmp_path, preflight_mode="off"))
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    out = await rt.run("A", context=ExecutionContext(run_id="r1"))
    assert out.output == "ok"


@pytest.mark.asyncio
async def test_sdk_native_mode_passes_openai_backend_to_agent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("skills_runtime.core.agent.Agent", _FakeAgent)

    rt = Runtime(RuntimeConfig(mode="sdk_native", workspace_root=tmp_path, preflight_mode="off"))
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    _ = await rt.run("A", context=ExecutionContext(run_id="r1"))

    agent = _FakeAgent.last_instance
    assert agent is not None
    backend = agent.kwargs.get("backend")
    assert backend is not None
    assert backend.__class__.__name__ == "_UsageTapBackend"
    assert getattr(backend, "_backend").__class__.__name__ == "OpenAIChatCompletionsBackend"
