from __future__ import annotations

"""
升级护栏（skills-runtime-sdk==0.1.8）：
- 上游 `sandbox.profile` preset 在 0.1.7 调整为 baseline defaults（仅填缺省，不覆盖显式字段），且该语义在 0.1.8 不得回归；
- 本仓需要用离线回归把该语义固化，避免后续升级导致沙箱默认策略“意外变宽/变窄”。
"""


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

