from __future__ import annotations

from pathlib import Path

from agently_skills_runtime.adapters.upstream import check_module_under_root, find_module_origin


def test_find_module_origin_missing_returns_none() -> None:
    assert find_module_origin("agently_skills_runtime___definitely_missing") is None


def test_check_module_under_root_missing_module_is_not_ok() -> None:
    res = check_module_under_root(
        module_name="agently_skills_runtime___definitely_missing",
        expected_root=Path("."),
    )
    assert res.ok is False
    assert "module not found" in res.message

