"""
config.py

配置加载（v0.2.0 主线）。

原则：
- protocol/ 与 runtime/ 不依赖上游；
- 配置加载仅负责把 YAML/字典解析为运行时可用的数据结构；
- 上游安装与适配器启用是“可选能力”，不应影响核心协议/运行时的可测试性。
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .runtime.engine import RuntimeConfig


def load_runtime_config_from_dict(data: dict[str, Any]) -> RuntimeConfig:
    """
    从 dict 构造 `RuntimeConfig`。

    参数：
    - data：配置字典（通常来自 YAML）。

    返回：
    - RuntimeConfig

    异常：
    - ConfigurationError：字段缺失、字段类型不匹配、或包含未知字段。
    """

    if not isinstance(data, dict):
        raise ConfigurationError("runtime config must be a dict")

    allowed_keys = {
        "workspace_root",
        "sdk_config_paths",
        "agently_agent",
        "preflight_mode",
        "max_loop_iterations",
        "max_depth",
        "skill_uri_allowlist",
    }
    unknown = set(data.keys()) - allowed_keys
    if unknown:
        raise ConfigurationError(f"unknown runtime config keys: {sorted(unknown)}")

    workspace_root = data.get("workspace_root", ".")
    if not isinstance(workspace_root, str):
        raise ConfigurationError("workspace_root must be a string")

    sdk_config_paths = data.get("sdk_config_paths", [])
    if not isinstance(sdk_config_paths, list) or not all(isinstance(p, str) for p in sdk_config_paths):
        raise ConfigurationError("sdk_config_paths must be a list[str]")

    preflight_mode = data.get("preflight_mode", "error")
    if not isinstance(preflight_mode, str):
        raise ConfigurationError("preflight_mode must be a string")

    max_loop_iterations = data.get("max_loop_iterations", 200)
    if not isinstance(max_loop_iterations, int) or max_loop_iterations <= 0:
        raise ConfigurationError("max_loop_iterations must be a positive int")

    max_depth = data.get("max_depth", 10)
    if not isinstance(max_depth, int) or max_depth <= 0:
        raise ConfigurationError("max_depth must be a positive int")

    skill_uri_allowlist = data.get("skill_uri_allowlist", [])
    if not isinstance(skill_uri_allowlist, list) or not all(isinstance(v, str) for v in skill_uri_allowlist):
        raise ConfigurationError("skill_uri_allowlist must be a list[str]")

    return RuntimeConfig(
        workspace_root=workspace_root,
        sdk_config_paths=list(sdk_config_paths),
        agently_agent=data.get("agently_agent"),
        preflight_mode=preflight_mode,
        max_loop_iterations=max_loop_iterations,
        max_depth=max_depth,
        skill_uri_allowlist=list(skill_uri_allowlist),
    )


def load_runtime_config(path: str | Path) -> RuntimeConfig:
    """
    从 YAML 文件加载 `RuntimeConfig`。

    参数：
    - path：YAML 文件路径。

    返回：
    - RuntimeConfig

    异常：
    - ConfigurationError：文件不存在、无法解析、或字段不合法。
    """

    p = Path(path)
    if not p.exists():
        raise ConfigurationError(f"config file not found: {p}")

    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise ConfigurationError("PyYAML is required to load YAML config files") from exc

    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ConfigurationError(f"failed to parse yaml: {p}") from exc

    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigurationError("top-level YAML must be a mapping")

    return load_runtime_config_from_dict(data)


def dump_runtime_config_to_dict(config: RuntimeConfig) -> dict[str, Any]:
    """
    将 `RuntimeConfig` 转为可序列化 dict（便于写入 report/debug）。

    参数：
    - config：RuntimeConfig

    返回：
    - dict
    """

    return dict(asdict(config))
