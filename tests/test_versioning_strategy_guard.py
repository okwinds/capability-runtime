from __future__ import annotations

from skills_runtime.core.errors import FrameworkIssue

from capability_runtime.sdk_lifecycle import _normalize_skills_config_for_skills_runtime


def _codes(issues: list[FrameworkIssue]) -> list[str]:
    return [str(getattr(issue, "code", "") or "") for issue in issues]


def test_missing_versioning_strategy_is_allowed() -> None:
    normalized, issues = _normalize_skills_config_for_skills_runtime({})

    assert normalized == {}
    assert _codes(issues) == []


def test_empty_versioning_strategy_is_allowed() -> None:
    normalized, issues = _normalize_skills_config_for_skills_runtime({"versioning": {"strategy": ""}})

    assert normalized == {"versioning": {"strategy": ""}}
    assert _codes(issues) == []


def test_todo_versioning_strategy_surfaces_drift_issue_for_bare_skills_config() -> None:
    normalized, issues = _normalize_skills_config_for_skills_runtime({"versioning": {"strategy": "TODO"}})

    assert normalized == {"versioning": {"strategy": "TODO"}}
    assert len(issues) == 1
    issue = issues[0]
    assert str(issue.code) == "SKILL_CONFIG_VERSIONING_STRATEGY_DRIFT"
    assert issue.details == {"path": "versioning.strategy", "value": "TODO"}


def test_todo_versioning_strategy_surfaces_drift_issue_for_full_sdk_config() -> None:
    normalized, issues = _normalize_skills_config_for_skills_runtime(
        {"skills": {"versioning": {"strategy": "TODO"}}}
    )

    assert normalized == {"versioning": {"strategy": "TODO"}}
    assert len(issues) == 1
    issue = issues[0]
    assert str(issue.code) == "SKILL_CONFIG_VERSIONING_STRATEGY_DRIFT"
    assert issue.details == {"path": "skills.versioning.strategy", "value": "TODO"}


def test_explicit_non_empty_versioning_strategy_is_allowed() -> None:
    normalized, issues = _normalize_skills_config_for_skills_runtime({"versioning": {"strategy": "hash"}})

    assert normalized == {"versioning": {"strategy": "hash"}}
    assert _codes(issues) == []

