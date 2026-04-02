from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "check_release_tag_version.py"


def _load_release_guard_module():
    spec = importlib.util.spec_from_file_location("release_guard", _SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"failed to load script: {_SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_guard_accepts_current_tag() -> None:
    module = _load_release_guard_module()
    tag_version, pyproject_version, module_version = module.validate_versions(
        release_tag="v0.0.7",
        pyproject_path=_REPO_ROOT / "pyproject.toml",
        init_path=_REPO_ROOT / "src" / "capability_runtime" / "__init__.py",
    )
    assert tag_version == pyproject_version == module_version == "0.0.7"


def test_release_guard_rejects_mismatch() -> None:
    module = _load_release_guard_module()
    with pytest.raises(ValueError, match="release version mismatch"):
        module.validate_versions(
            release_tag="v9.9.9",
            pyproject_path=_REPO_ROOT / "pyproject.toml",
            init_path=_REPO_ROOT / "src" / "capability_runtime" / "__init__.py",
        )
