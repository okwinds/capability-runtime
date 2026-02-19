from __future__ import annotations

import pytest

from agently_skills_runtime.config import load_runtime_config, load_runtime_config_from_dict
from agently_skills_runtime.errors import ConfigurationError


def test_load_runtime_config_from_dict_defaults() -> None:
    cfg = load_runtime_config_from_dict({})
    assert cfg.workspace_root == "."
    assert cfg.sdk_config_paths == []
    assert cfg.skill_uri_allowlist == []
    assert cfg.preflight_mode == "error"
    assert cfg.max_loop_iterations == 200
    assert cfg.max_depth == 10


def test_load_runtime_config_from_dict_unknown_key_raises() -> None:
    with pytest.raises(ConfigurationError):
        load_runtime_config_from_dict({"unknown": 1})


def test_load_runtime_config_from_dict_accepts_skill_uri_allowlist() -> None:
    cfg = load_runtime_config_from_dict({"skill_uri_allowlist": ["file://", "https://trusted.example/"]})
    assert cfg.skill_uri_allowlist == ["file://", "https://trusted.example/"]


def test_load_runtime_config_from_dict_invalid_skill_uri_allowlist_type_raises() -> None:
    with pytest.raises(ConfigurationError):
        load_runtime_config_from_dict({"skill_uri_allowlist": "file://"})


def test_load_runtime_config_from_yaml_accepts_skill_uri_allowlist(tmp_path) -> None:
    config_path = tmp_path / "runtime.yaml"
    config_path.write_text("skill_uri_allowlist:\n  - file://\n", encoding="utf-8")

    cfg = load_runtime_config(config_path)
    assert cfg.skill_uri_allowlist == ["file://"]
