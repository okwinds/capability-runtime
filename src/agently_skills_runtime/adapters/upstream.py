"""
adapters/upstream.py

上游版本/来源校验（可选）。

背景：
- 本仓库要求“不侵入上游”，通常会在工作区中引入上游 fork（例如 `../Agently`、`../skills-runtime-sdk`）。
- 业务方可能希望在运行前做一次“来源校验”，避免意外导入到了错误的 site-packages 版本或非预期 fork。

本模块提供“最小、可复用”的校验函数：
- 不强依赖上游包是否已安装；
- 优先通过 `importlib.util.find_spec()` 获取 origin 路径，避免 import 触发副作用。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class UpstreamVerificationMode(str, Enum):
    """上游校验模式。"""

    OFF = "off"
    WARN = "warn"
    STRICT = "strict"


@dataclass(frozen=True)
class UpstreamCheckResult:
    """
    单个模块的校验结果。

    字段：
    - `module`：模块名（例如 `agently`）
    - `origin`：解析到的模块 origin 文件路径（可能为空）
    - `expected_root`：期望的根目录（可为空）
    - `ok`：是否通过校验
    - `message`：可诊断信息
    """

    module: str
    origin: Optional[str]
    expected_root: Optional[str]
    ok: bool
    message: str


def _normalize_path(p: str | Path) -> Path:
    """路径归一化（resolve + expanduser），用于一致比较。"""

    return Path(p).expanduser().resolve()


def find_module_origin(module_name: str) -> Optional[str]:
    """
    获取模块 origin 文件路径（尽量不触发 import）。

    参数：
    - module_name：模块名（例如 `agently`）

    返回：
    - origin 路径字符串；若找不到返回 None
    """

    import importlib.util

    spec = importlib.util.find_spec(module_name)
    if spec is None:
        return None
    return spec.origin


def check_module_under_root(*, module_name: str, expected_root: str | Path) -> UpstreamCheckResult:
    """
    校验某模块的 origin 是否位于期望根目录之下。

    参数：
    - module_name：模块名
    - expected_root：期望根目录（例如 `../Agently`）

    返回：
    - UpstreamCheckResult
    """

    origin = find_module_origin(module_name)
    exp = _normalize_path(expected_root)

    if origin is None:
        return UpstreamCheckResult(
            module=module_name,
            origin=None,
            expected_root=str(exp),
            ok=False,
            message="module not found (not installed / not importable)",
        )

    try:
        origin_path = _normalize_path(origin)
    except Exception:
        return UpstreamCheckResult(
            module=module_name,
            origin=origin,
            expected_root=str(exp),
            ok=False,
            message="module origin path is not a valid filesystem path",
        )

    ok = str(origin_path).startswith(str(exp) + "/") or origin_path == exp
    msg = "ok" if ok else f"origin is not under expected_root: origin={origin_path}, expected_root={exp}"
    return UpstreamCheckResult(module=module_name, origin=str(origin_path), expected_root=str(exp), ok=ok, message=msg)

