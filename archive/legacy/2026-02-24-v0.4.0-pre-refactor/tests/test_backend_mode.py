from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from agent_sdk.config.defaults import load_default_config_dict
from agent_sdk.config.loader import load_config_dicts

from agently_skills_runtime.bridge import AgentlySkillsRuntime, AgentlySkillsRuntimeConfig


class _FakeAgent:
    def __init__(self, *, backend: Any = None, **kwargs: Any) -> None:
        self.backend = backend
        self.kwargs = kwargs


def test_runtime_config_default_backend_mode():
    cfg = AgentlySkillsRuntimeConfig(workspace_root=Path("."), config_paths=[])
    assert cfg.backend_mode == "agently_openai_compatible"


def test_runtime_unknown_backend_mode_raises(tmp_path):
    cfg = AgentlySkillsRuntimeConfig(workspace_root=tmp_path, config_paths=[])
    cfg = replace(cfg, backend_mode="unknown")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        AgentlySkillsRuntime(agently_agent=object(), config=cfg)


def test_sdk_backend_mode_does_not_call_agently_requester_factory(monkeypatch, tmp_path):
    cfg = AgentlySkillsRuntimeConfig(workspace_root=tmp_path, config_paths=[], backend_mode="sdk_openai_chat_completions")

    import agently_skills_runtime.bridge as rt_mod

    monkeypatch.setattr(rt_mod, "build_openai_compatible_requester_factory", lambda **_: (_ for _ in ()).throw(AssertionError))
    AgentlySkillsRuntime(agently_agent=object(), config=cfg)


def test_sdk_backend_mode_passes_openai_backend_to_agent(monkeypatch, tmp_path):
    cfg = AgentlySkillsRuntimeConfig(workspace_root=tmp_path, config_paths=[], backend_mode="sdk_openai_chat_completions")

    import agently_skills_runtime.bridge as rt_mod

    monkeypatch.setattr(rt_mod, "Agent", _FakeAgent)
    rt = AgentlySkillsRuntime(agently_agent=object(), config=cfg)
    agent = rt._get_or_create_agent()
    assert agent.backend is not None
    assert agent.backend.__class__.__name__ == "OpenAIChatCompletionsBackend"


def test_sdk_backend_mode_uses_env_store_as_api_key_override(monkeypatch, tmp_path):
    sdk_cfg = load_config_dicts([load_default_config_dict()])
    key_name = str(getattr(sdk_cfg.llm, "api_key_env") or "")
    assert key_name

    cfg = AgentlySkillsRuntimeConfig(workspace_root=tmp_path, config_paths=[], backend_mode="sdk_openai_chat_completions")

    import agently_skills_runtime.bridge as rt_mod

    monkeypatch.setattr(rt_mod, "Agent", _FakeAgent)
    rt = AgentlySkillsRuntime(agently_agent=object(), config=cfg, env_store={key_name: "k"})
    agent = rt._get_or_create_agent()
    assert getattr(agent.backend, "_api_key_override") == "k"


def test_sdk_backend_mode_does_not_require_agently_agent_shape(monkeypatch, tmp_path):
    cfg = AgentlySkillsRuntimeConfig(workspace_root=tmp_path, config_paths=[], backend_mode="sdk_openai_chat_completions")

    import agently_skills_runtime.bridge as rt_mod

    monkeypatch.setattr(rt_mod, "Agent", _FakeAgent)
    rt = AgentlySkillsRuntime(agently_agent=object(), config=cfg)
    rt._get_or_create_agent()


def test_sdk_backend_mode_api_key_override_can_be_none(monkeypatch, tmp_path):
    cfg = AgentlySkillsRuntimeConfig(workspace_root=tmp_path, config_paths=[], backend_mode="sdk_openai_chat_completions")

    import agently_skills_runtime.bridge as rt_mod

    monkeypatch.setattr(rt_mod, "Agent", _FakeAgent)
    rt = AgentlySkillsRuntime(agently_agent=object(), config=cfg, env_store={})
    agent = rt._get_or_create_agent()
    assert hasattr(agent.backend, "_api_key_override")
    assert getattr(agent.backend, "_api_key_override") is None


def test_agently_backend_mode_calls_requester_factory(monkeypatch, tmp_path):
    called: Dict[str, Any] = {"ok": False}

    def _factory(*, agently_agent: Any):
        called["ok"] = True

        def _rf():
            raise RuntimeError("not used in this test")

        return _rf

    class _FakeAgentlyChatBackend:
        def __init__(self, *, config: Any) -> None:
            self.config = config

    cfg = AgentlySkillsRuntimeConfig(workspace_root=tmp_path, config_paths=[], backend_mode="agently_openai_compatible")

    import agently_skills_runtime.bridge as rt_mod

    monkeypatch.setattr(rt_mod, "build_openai_compatible_requester_factory", _factory)
    monkeypatch.setattr(rt_mod, "AgentlyChatBackend", _FakeAgentlyChatBackend)
    monkeypatch.setattr(rt_mod, "Agent", _FakeAgent)

    rt = AgentlySkillsRuntime(agently_agent=object(), config=cfg)
    assert called["ok"] is True
    agent = rt._get_or_create_agent()
    assert agent.backend.__class__.__name__ == "_FakeAgentlyChatBackend"


def test_preflight_does_not_create_agent(monkeypatch, tmp_path):
    cfg = AgentlySkillsRuntimeConfig(workspace_root=tmp_path, config_paths=[], backend_mode="sdk_openai_chat_completions")

    import agently_skills_runtime.bridge as rt_mod

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Agent must not be constructed during preflight")

    monkeypatch.setattr(rt_mod, "Agent", _boom)

    rt = AgentlySkillsRuntime(agently_agent=object(), config=cfg)
    issues = rt.preflight()
    assert isinstance(issues, list)


def test_run_uses_lazy_agent_construction(monkeypatch, tmp_path):
    cfg = AgentlySkillsRuntimeConfig(workspace_root=tmp_path, config_paths=[], backend_mode="sdk_openai_chat_completions")

    import agently_skills_runtime.bridge as rt_mod

    # Ensure __init__ does not create the Agent eagerly.
    created: Dict[str, bool] = {"created": False}

    class _LazyAgent(_FakeAgent):
        def __init__(self, **kwargs: Any) -> None:
            created["created"] = True
            super().__init__(**kwargs)

    monkeypatch.setattr(rt_mod, "Agent", _LazyAgent)
    rt = AgentlySkillsRuntime(agently_agent=object(), config=cfg)
    assert created["created"] is False
    rt._get_or_create_agent()
    assert created["created"] is True
