from __future__ import annotations

"""
回归护栏：重构后不再保留“上游 fork 校验（UpstreamVerificationMode）”的独立概念。

依据：
- docs/context/refactoring-spec.md 2.3.3（概念删除）：UpstreamVerificationMode 简化为 preflight 的一个检查项

本仓主线不再提供：
- upstream_verification_mode
- agently_fork_root / skills_runtime_sdk_fork_root

说明：
- 本文件保留用于防止历史概念回流到主线 API。
"""

from capability_runtime.config import RuntimeConfig


def test_runtime_config_has_no_upstream_verification_fields() -> None:
    cfg = RuntimeConfig()
    assert not hasattr(cfg, "upstream_verification_mode")
    assert not hasattr(cfg, "agently_fork_root")
    assert not hasattr(cfg, "skills_runtime_sdk_fork_root")

