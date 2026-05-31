from __future__ import annotations

"""Agently bridge capability diagnostics.

本模块只提供安装态 / import 源 / requester 能力摘要，不承载业务逻辑，也不暴露
Agently 原生对象给下游。
"""

import importlib
import importlib.metadata as importlib_metadata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


@dataclass(frozen=True)
class AgentlyBridgeDiagnostics:
    """Agently bridge 的脱敏能力诊断。"""

    installed_version: str | None
    imported_from: str | None
    requester_strategy: str
    supports_openai_responses: bool
    metadata_source_consistent: bool


def collect_agently_bridge_diagnostics(*, requester_strategy: str) -> AgentlyBridgeDiagnostics:
    """收集当前安装态 Agently 的 bridge 诊断摘要。"""

    installed_version = _installed_agently_version()
    imported_from = _imported_agently_file()
    return AgentlyBridgeDiagnostics(
        installed_version=installed_version,
        imported_from=imported_from,
        requester_strategy=str(requester_strategy),
        supports_openai_responses=_supports_openai_responses(),
        metadata_source_consistent=_metadata_source_consistent(imported_from=imported_from),
    )


def summarize_agently_bridge_diagnostics(diagnostics: AgentlyBridgeDiagnostics) -> Dict[str, Any]:
    """把 diagnostics 转成可写入 `NodeReport.bridge["agently"]` 的脱敏 dict。"""

    return {
        "installed_version": diagnostics.installed_version,
        "imported_from": diagnostics.imported_from,
        "requester_strategy": diagnostics.requester_strategy,
        "supports_openai_responses": diagnostics.supports_openai_responses,
        "metadata_source_consistent": diagnostics.metadata_source_consistent,
    }


def _installed_agently_version() -> str | None:
    try:
        return importlib_metadata.version("agently")
    except importlib_metadata.PackageNotFoundError:
        return None


def _imported_agently_file() -> str | None:
    try:
        module = importlib.import_module("agently")
    except ModuleNotFoundError:
        return None
    path = getattr(module, "__file__", None)
    if not isinstance(path, str) or not path:
        return None
    return str(Path(path).resolve())


def _supports_openai_responses() -> bool:
    try:
        importlib.import_module("agently.builtins.plugins.ModelRequester.OpenAIResponsesCompatible")
        return True
    except ModuleNotFoundError:
        return False


def _metadata_source_consistent(*, imported_from: str | None) -> bool:
    if imported_from is None:
        return False
    try:
        distribution = importlib_metadata.distribution("agently")
    except importlib_metadata.PackageNotFoundError:
        return False
    dist_root = Path(distribution.locate_file("")).resolve()
    imported_path = Path(imported_from).resolve()
    return imported_path == dist_root or dist_root in imported_path.parents


__all__ = [
    "AgentlyBridgeDiagnostics",
    "collect_agently_bridge_diagnostics",
    "summarize_agently_bridge_diagnostics",
]
