from __future__ import annotations

from pathlib import Path

import pytest

from agently_skills_runtime.config import RuntimeConfig, normalize_workspace_root


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
