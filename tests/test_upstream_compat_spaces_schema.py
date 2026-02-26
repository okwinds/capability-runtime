from __future__ import annotations

"""
上游兼容层离线护栏：skills spaces schema（account/domain ↔ namespace）。

说明：
- 上游 skills-runtime-sdk 在 v0.1.5 引入 `skills.spaces[].namespace` 并拒绝 legacy 字段；
- 本仓需要在进入上游 loader 前做最小转换，并在无法无损映射时 fail-closed。
"""

import pytest

from skills_runtime.core.errors import FrameworkError

from agently_skills_runtime.runtime import _normalize_skills_config_for_skills_runtime
from agently_skills_runtime.upstream_compat import normalize_spaces_for_upstream


def test_spaces_account_domain_to_namespace_ok():
    spaces = [{"id": "sp1", "account": "aa", "domain": "bb", "sources": ["s1"], "enabled": True}]
    normalized, warnings = normalize_spaces_for_upstream(spaces=spaces, target_schema="namespace")
    assert normalized is not None
    assert warnings
    assert normalized[0]["namespace"] == "aa:bb"
    assert "account" not in normalized[0]
    assert "domain" not in normalized[0]


def test_spaces_namespace_to_account_domain_ok_when_two_segments():
    spaces = [{"id": "sp1", "namespace": "aa:bb", "sources": ["s1"], "enabled": True}]
    normalized, warnings = normalize_spaces_for_upstream(spaces=spaces, target_schema="account_domain")
    assert normalized is not None
    assert warnings
    assert normalized[0]["account"] == "aa"
    assert normalized[0]["domain"] == "bb"
    assert "namespace" not in normalized[0]


def test_spaces_namespace_to_account_domain_fail_closed_when_multi_segment():
    spaces = [{"id": "sp1", "namespace": "aa:bb:cc", "sources": ["s1"], "enabled": True}]
    normalized, warnings = normalize_spaces_for_upstream(spaces=spaces, target_schema="account_domain")
    assert normalized is None
    assert warnings


def test_runtime_normalize_fail_closed_when_namespace_not_mappable(monkeypatch):
    # 模拟：当前上游仍为 legacy schema，但调用方传入多段 namespace（无法映射回 account/domain）。
    monkeypatch.setattr(
        "agently_skills_runtime.upstream_compat.detect_skills_space_schema",
        lambda: "account_domain",
    )
    with pytest.raises(FrameworkError) as ei:
        _normalize_skills_config_for_skills_runtime(
            {
                "spaces": [{"id": "sp1", "namespace": "aa:bb:cc", "sources": ["s1"], "enabled": True}],
                "sources": [],
            }
        )
    assert ei.value.code == "SKILL_CONFIG_SPACES_SCHEMA_INCOMPATIBLE"


def test_runtime_normalize_converts_when_target_namespace(monkeypatch):
    monkeypatch.setattr(
        "agently_skills_runtime.upstream_compat.detect_skills_space_schema",
        lambda: "namespace",
    )
    out = _normalize_skills_config_for_skills_runtime(
        {
            "spaces": [{"id": "sp1", "account": "aa", "domain": "bb", "sources": ["s1"], "enabled": True}],
            "sources": [],
        }
    )
    assert isinstance(out, dict)
    assert out["spaces"][0]["namespace"] == "aa:bb"

