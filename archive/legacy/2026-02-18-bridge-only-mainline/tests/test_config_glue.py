from pathlib import Path

import pytest

from agently_skills_runtime.config import BridgeConfigModel, resolve_paths


def test_bridge_config_rejects_extra_fields():
    with pytest.raises(Exception):
        BridgeConfigModel.model_validate({"workspace_root": ".", "sdk_config_paths": [], "extra": 1})


def test_bridge_config_defaults():
    cfg = BridgeConfigModel.model_validate({})
    assert cfg.workspace_root == "."
    assert cfg.sdk_config_paths == []
    assert cfg.preflight_mode == "error"
    assert cfg.backend_mode == "agently_openai_compatible"
    assert cfg.upstream_verification_mode == "warn"
    assert cfg.agently_fork_root is None
    assert cfg.skills_runtime_sdk_fork_root is None


def test_bridge_config_to_runtime_config_roundtrip():
    cfg = BridgeConfigModel.model_validate(
        {
            "workspace_root": "/w",
            "sdk_config_paths": ["a.yaml", "b.yaml"],
            "preflight_mode": "warn",
            "backend_mode": "sdk_openai_chat_completions",
            "upstream_verification_mode": "strict",
            "agently_fork_root": "/fork/agently",
            "skills_runtime_sdk_fork_root": "/fork/skills-runtime-sdk",
        }
    )
    out = cfg.to_runtime_config()
    assert out["workspace_root"] == "/w"
    assert out["sdk_config_paths"] == ["a.yaml", "b.yaml"]
    assert out["preflight_mode"] == "warn"
    assert out["backend_mode"] == "sdk_openai_chat_completions"
    assert out["upstream_verification_mode"] == "strict"
    assert out["agently_fork_root"] == "/fork/agently"
    assert out["skills_runtime_sdk_fork_root"] == "/fork/skills-runtime-sdk"


def test_resolve_paths_makes_absolute_paths(tmp_path):
    root = tmp_path / "w"
    root.mkdir()
    (root / "a.yaml").write_text("x: 1\n", encoding="utf-8")
    out = resolve_paths(workspace_root=root, sdk_config_paths=["a.yaml"])
    assert out[0].is_absolute()
    assert out[0].name == "a.yaml"


def test_resolve_paths_expands_user(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    p = home / "a.yaml"
    p.write_text("x: 1\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))

    out = resolve_paths(workspace_root=Path("."), sdk_config_paths=["~/a.yaml"])
    assert out[0] == p.resolve()


def test_resolve_paths_keeps_absolute_path():
    out = resolve_paths(workspace_root=Path("."), sdk_config_paths=["/tmp/a.yaml"])
    assert out[0] == Path("/tmp/a.yaml").resolve()


def test_resolve_paths_resolves_parent_segments(tmp_path):
    root = tmp_path / "w"
    nested = root / "nested"
    nested.mkdir(parents=True)
    target = root / "a.yaml"
    target.write_text("x: 1\n", encoding="utf-8")

    out = resolve_paths(workspace_root=nested, sdk_config_paths=["../a.yaml"])
    assert out[0] == target.resolve()


def test_resolve_paths_allows_multiple_paths(tmp_path):
    root = tmp_path / "w"
    root.mkdir()
    (root / "a.yaml").write_text("x: 1\n", encoding="utf-8")
    (root / "b.yaml").write_text("x: 2\n", encoding="utf-8")
    out = resolve_paths(workspace_root=root, sdk_config_paths=["a.yaml", "b.yaml"])
    assert [p.name for p in out] == ["a.yaml", "b.yaml"]


def test_resolve_paths_works_with_nonexistent_file(tmp_path):
    root = tmp_path / "w"
    root.mkdir()
    out = resolve_paths(workspace_root=root, sdk_config_paths=["missing.yaml"])
    assert out[0] == (root / "missing.yaml").resolve()


def test_bridge_config_preflight_mode_accepts_any_string_but_runtime_validates_elsewhere():
    cfg = BridgeConfigModel.model_validate({"preflight_mode": "custom"})
    assert cfg.preflight_mode == "custom"


def test_bridge_config_upstream_mode_accepts_any_string_but_runtime_validates_elsewhere():
    cfg = BridgeConfigModel.model_validate({"upstream_verification_mode": "custom"})
    assert cfg.upstream_verification_mode == "custom"
