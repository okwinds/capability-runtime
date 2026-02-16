"""
后端配置（环境变量驱动）。

约束：
- 默认 demo 模式必须离线可跑；
- 真实模式（real）仅作为可选集成冒烟入口。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal


RunMode = Literal["demo", "real"]


@dataclass(frozen=True)
class Settings:
    workspace_root: Path
    sdk_config_paths: List[Path]
    run_mode: RunMode


def load_settings() -> Settings:
    """
    从环境变量加载 Settings。

    返回：
    - Settings（workspace_root / sdk_config_paths / run_mode）
    """

    workspace_root = Path(os.getenv("AGENTLY_SKILLS_WEB_WORKSPACE_ROOT", ".runtime/workspace")).expanduser().resolve()

    raw_paths = os.getenv("AGENTLY_SKILLS_WEB_SDK_CONFIG_PATHS", "config/sdk.demo.yaml")
    sdk_paths: List[Path] = []
    for part in [p.strip() for p in raw_paths.split(",") if p.strip()]:
        p = Path(part).expanduser()
        if not p.is_absolute():
            p = (Path(__file__).resolve().parents[3] / part).resolve()
        sdk_paths.append(p)

    run_mode = os.getenv("AGENTLY_SKILLS_WEB_RUN_MODE", "demo").strip().lower()
    if run_mode not in ("demo", "real"):
        run_mode = "demo"

    return Settings(workspace_root=workspace_root, sdk_config_paths=sdk_paths, run_mode=run_mode)  # type: ignore[arg-type]
