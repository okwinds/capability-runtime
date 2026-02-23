"""
Approvals profiles：阻塞等待审批的最佳实践配置与校验。

目标：
- 提供可移植的 dev/prod profile 模板（不绑定业务 UI）；
- 强制校验 `approval_timeout_ms` 与 `max_wall_time_sec` 的关系，避免“审批永远等不到结果”。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class ApprovalsProfile(BaseModel):
    """
    ApprovalsProfile（可移植配置模板）。

    参数：
    - name：profile 名称（dev/prod/custom）
    - approval_timeout_ms：等待人类审批的最长时间（超时按 denied）
    - max_wall_time_sec：一次 run 的最大墙钟时间（预算）
    - buffer_ms：安全 buffer（避免 wall-time 先于 approval timeout 触发）
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    approval_timeout_ms: int = Field(ge=1)
    max_wall_time_sec: int = Field(ge=1)
    buffer_ms: int = Field(default=60_000, ge=0)

    def to_sdk_overlay(self) -> Dict[str, Any]:
        """
        转为 agent_sdk 配置 overlays。

        返回：
        - overlays dict（可写入 YAML 并作为 config_paths 传入）
        """

        return {
            "run": {"max_wall_time_sec": int(self.max_wall_time_sec)},
            "safety": {"approval_timeout_ms": int(self.approval_timeout_ms)},
        }


@dataclass(frozen=True)
class ApprovalsProfiles:
    """
    推荐 profiles 集合（可作为默认值参考）。

    注意：这些值仅是框架建议；调用方必须根据实际审批时延与节点预算调整。
    """

    dev: ApprovalsProfile = field(
        default_factory=lambda: ApprovalsProfile(
            name="dev",
            approval_timeout_ms=60_000,
            max_wall_time_sec=600,
            buffer_ms=60_000,
        )
    )
    prod: ApprovalsProfile = field(
        default_factory=lambda: ApprovalsProfile(
            name="prod",
            approval_timeout_ms=600_000,
            max_wall_time_sec=1800,
            buffer_ms=120_000,
        )
    )


def validate_approvals_profile(*, profile: ApprovalsProfile) -> None:
    """
    校验 approvals profile 的 timeout 关系。

    规则：
    - approval_timeout_ms <= max_wall_time_sec*1000 - buffer_ms

    参数：
    - profile：待校验 profile

    异常：
    - ValueError：关系不满足时抛出（用于 fail-closed）
    """

    max_ms = int(profile.max_wall_time_sec) * 1000
    if int(profile.approval_timeout_ms) > max_ms - int(profile.buffer_ms):
        raise ValueError(
            "invalid approvals profile: approval_timeout_ms must be <= max_wall_time_sec*1000 - buffer_ms "
            f"(got approval_timeout_ms={profile.approval_timeout_ms}, max_wall_time_sec={profile.max_wall_time_sec}, buffer_ms={profile.buffer_ms})"
        )
