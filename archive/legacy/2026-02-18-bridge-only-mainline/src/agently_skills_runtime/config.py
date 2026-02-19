"""
配置胶水（Bridge Config → SDK overlays）。

对齐规格：
- `docs/specs/engineering-spec/04_Operations/CONFIGURATION.md`
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class BridgeConfigModel(BaseModel):
    """
    桥接层配置模型（仅本仓库关心的最小集合）。

    说明：
    - SDK 的完整配置（skills/spaces/sources/safety/models/...）不在这里重写；
      调用方应通过 `sdk_config_paths` 传入 overlays。
    """

    model_config = ConfigDict(extra="forbid")

    workspace_root: str = Field(default=".", description="SDK workspace_root（相对路径会相对于当前进程 cwd 解析）")
    sdk_config_paths: List[str] = Field(default_factory=list, description="SDK overlays 路径列表（后者覆盖前者）")
    preflight_mode: str = Field(default="error", description="error|warn|off（生产默认 error）")
    backend_mode: str = Field(
        default="agently_openai_compatible",
        description="agently_openai_compatible|sdk_openai_chat_completions（默认复用 Agently；必要时显式切到 SDK 原生 OpenAI backend）",
    )
    upstream_verification_mode: str = Field(
        default="warn",
        description="off|warn|strict（是否校验当前导入模块来自预期 fork 路径）",
    )
    agently_fork_root: Optional[str] = Field(
        default=None,
        description="Agently fork 根目录（可选；strict 下建议必填）",
    )
    skills_runtime_sdk_fork_root: Optional[str] = Field(
        default=None,
        description="skills-runtime-sdk fork 根目录（可选；strict 下建议必填）",
    )

    def to_runtime_config(self) -> Dict[str, Any]:
        """转换为构造 runtime 所需的参数 dict（便于宿主直接展开）。"""

        return self.model_dump()


def resolve_paths(*, workspace_root: Path, sdk_config_paths: List[str]) -> List[Path]:
    """
    把 overlays 路径解析为绝对路径列表。

    参数：
    - `workspace_root`：workspace 根目录（用于相对 overlays 解析）
    - `sdk_config_paths`：overlays 路径（str）
    """

    root = Path(workspace_root).expanduser().resolve()
    out: List[Path] = []
    for raw in sdk_config_paths:
        p = Path(str(raw)).expanduser()
        if not p.is_absolute():
            p = (root / p).resolve()
        else:
            p = p.resolve()
        out.append(p)
    return out
