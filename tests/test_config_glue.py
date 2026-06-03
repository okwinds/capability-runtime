from __future__ import annotations

from pathlib import Path

import pytest

from capability_runtime.config import RuntimeConfig, normalize_workspace_root


def test_runtime_config_defaults():
    """
    回归护栏：重构后配置模型收敛为 RuntimeConfig（不再保留 BridgeConfigModel）。
    """

    cfg = RuntimeConfig()
    assert cfg.mode == "bridge"
    assert cfg.workspace_root is None
    assert cfg.sdk_config_paths == []
    assert cfg.preflight_mode == "error"
    assert cfg.env_vars == {}
    assert cfg.requester_strategy == "chat_completions"
    assert cfg.agently_requester is None
    assert cfg.effective_requester_strategy == "chat_completions"
    assert cfg.tool_choice_after_tool_result is None


def test_runtime_config_legacy_requester_alias_remains_available_when_neutral_field_is_default():
    cfg = RuntimeConfig(agently_requester="responses")

    assert cfg.requester_strategy == "responses"
    assert cfg.effective_requester_strategy == "responses"


def test_runtime_config_rejects_conflicting_legacy_requester_alias():
    with pytest.raises(ValueError, match="agently_requester conflicts with requester_strategy"):
        RuntimeConfig(requester_strategy="responses", agently_requester="chat_completions")


def test_runtime_config_rejects_legacy_alias_that_overrides_explicit_canonical_default():
    with pytest.raises(ValueError, match="agently_requester conflicts with requester_strategy"):
        RuntimeConfig(requester_strategy="chat_completions", agently_requester="responses")


def test_runtime_config_tool_choice_after_tool_result_is_explicit_opt_in():
    cfg = RuntimeConfig(tool_choice_after_tool_result="none")

    assert cfg.tool_choice_after_tool_result == "none"


def test_runtime_config_rejects_invalid_tool_choice_after_tool_result():
    import pytest

    with pytest.raises(ValueError, match="tool_choice_after_tool_result"):
        RuntimeConfig(tool_choice_after_tool_result="required")  # type: ignore[arg-type]


def test_runtime_config_rejects_invalid_requester_strategy():
    with pytest.raises(ValueError, match="requester_strategy"):
        RuntimeConfig(requester_strategy="response")  # type: ignore[arg-type]


def test_runtime_config_rejects_invalid_legacy_requester_alias():
    with pytest.raises(ValueError, match="agently_requester"):
        RuntimeConfig(agently_requester="chat_completion")  # type: ignore[arg-type]


def test_normalize_workspace_root_default_is_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = normalize_workspace_root(None)
    assert out == tmp_path.resolve()


def test_normalize_workspace_root_expands_user(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    w = normalize_workspace_root(Path("~/w"))
    assert w == (home / "w").resolve()


def test_normalize_workspace_root_resolves_relative_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = normalize_workspace_root(Path("./w"))
    assert out == (tmp_path / "w").resolve()
