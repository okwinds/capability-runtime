from __future__ import annotations

"""
升级护栏（skills-runtime-sdk==0.1.9）：
- 上游 `sandbox.profile` preset 在 0.1.7 调整为 baseline defaults（仅填缺省，不覆盖显式字段），且该语义在 0.1.9 不得回归；
- 本仓需要用离线回归把该语义固化，避免后续升级导致沙箱默认策略“意外变宽/变窄”。
"""

from capability_runtime.sdk_lifecycle import _sanitize_sdk_overlay_dict_for_loader


def test_upstream_sandbox_profile_does_not_override_explicit_fields() -> None:
    from skills_runtime.config.defaults import load_default_config_dict
    from skills_runtime.config.loader import load_config_dicts

    overlays = [
        load_default_config_dict(),
        {"sandbox": {"profile": "balanced", "default_policy": "none"}},
    ]
    cfg = load_config_dicts(overlays)
    assert cfg.sandbox.default_policy == "none"


def test_upstream_sandbox_profile_fills_missing_fields() -> None:
    from skills_runtime.config.defaults import load_default_config_dict
    from skills_runtime.config.loader import load_config_dicts

    overlays = [
        load_default_config_dict(),
        {"sandbox": {"profile": "balanced"}},
    ]
    cfg = load_config_dicts(overlays)
    assert cfg.sandbox.default_policy == "restricted"


def test_runtime_overlay_sanitizer_only_cleans_skills_root_and_keeps_sandbox_safety_run() -> None:
    sanitized, issues = _sanitize_sdk_overlay_dict_for_loader(
        {
            "sandbox": {"profile": "balanced", "default_policy": "none"},
            "safety": {"mode": "ask", "approval_timeout_ms": 60_000},
            "run": {"max_steps": 8},
            "skills": {
                "roots": ["/tmp/legacy"],
                "strictness": {"unknown_mention": "error"},
            },
        }
    )

    assert sanitized["sandbox"] == {"profile": "balanced", "default_policy": "none"}
    assert sanitized["safety"] == {"mode": "ask", "approval_timeout_ms": 60_000}
    assert sanitized["run"] == {"max_steps": 8}
    assert "roots" not in sanitized["skills"]
    assert sanitized["skills"]["strictness"] == {"unknown_mention": "error"}
    assert any(getattr(issue, "code", "") == "SKILL_CONFIG_LEGACY_ROOTS_UNSUPPORTED" for issue in issues)
