from __future__ import annotations

"""Agently Workspace/Recall preview 的中立适配层。"""

import re
from dataclasses import dataclass, field
from typing import Any

from ..types import NodeReport


_SENSITIVE_KEY_RE = re.compile(r"(authorization|api[_-]?key|secret|token|password|credential)", re.IGNORECASE)
_SENSITIVE_INLINE_RE = re.compile(
    r"(authorization\s*:\s*bearer\s+|api[_-]?key\s*[=:]\s*|token\s*[=:]\s*|secret\s*[=:]\s*)\S+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RuntimeContextRecordRef:
    """
    Runtime 侧 context record 引用。

    参数：
    - id：context record id
    - collection：所属集合
    - kind：可选记录类型
    - summary：脱敏后的短摘要
    """

    id: str
    collection: str
    kind: str | None = None
    summary: str | None = None


@dataclass(frozen=True)
class RuntimeRecallContextPack:
    """
    Runtime 侧 recall context pack。

    参数：
    - goal：构建 context pack 的目标
    - items：中立 record refs
    - omitted_count：因预算限制省略的数量
    - diagnostics：稳定诊断，不含上游 Workspace facade 或原始 provider 请求
    """

    goal: str
    items: tuple[RuntimeContextRecordRef, ...]
    omitted_count: int = 0
    diagnostics: dict[str, Any] = field(default_factory=dict)


async def build_recall_context_pack(
    workspace: Any,
    *,
    goal: str,
    scope: dict[str, Any] | None = None,
    budget: dict[str, Any] | None = None,
    profile: str = "auto",
) -> RuntimeRecallContextPack:
    """
    从 Agently Workspace `build_context()` 读取并归一为中立 context pack。

    参数：
    - workspace：Agently Workspace-like 对象；为 None 时返回 degraded pack
    - goal：context 构建目标
    - scope：可选检索范围
    - budget：可选预算，支持 `max_items`
    - profile：上游 profile 名称
    """

    if workspace is None or not callable(getattr(workspace, "build_context", None)):
        return RuntimeRecallContextPack(
            goal=str(goal),
            items=(),
            omitted_count=0,
            diagnostics={
                "degraded": True,
                "code": "WORKSPACE_BACKEND_UNAVAILABLE",
                "message": "workspace backend is not configured",
            },
        )

    try:
        raw_pack = await workspace.build_context(
            goal=str(goal),
            scope=dict(scope or {}),
            budget=dict(budget or {}),
            profile=str(profile),
        )
    except Exception as exc:
        return RuntimeRecallContextPack(
            goal=str(goal),
            items=(),
            omitted_count=0,
            diagnostics={
                "degraded": True,
                "code": "WORKSPACE_BUILD_CONTEXT_FAILED",
                "message": type(exc).__name__,
            },
        )

    raw_items = _extract_items(raw_pack)
    max_items = _max_items_from_budget(budget)
    selected = raw_items[:max_items]
    items = tuple(_record_ref_from_value(item) for item in selected)
    return RuntimeRecallContextPack(
        goal=str(goal),
        items=items,
        omitted_count=max(0, len(raw_items) - len(selected)),
        diagnostics={"degraded": False, "source": "runtime_context_pack"},
    )


async def write_node_report_summary(
    workspace: Any,
    report: NodeReport,
    *,
    collection: str = "runtime_evidence",
) -> RuntimeContextRecordRef:
    """
    将 NodeReport 的最小摘要写入 Workspace-like backend。

    参数：
    - workspace：Agently Workspace-like 对象
    - report：NodeReport 真相源摘要
    - collection：目标集合
    """

    if workspace is None or not callable(getattr(workspace, "put", None)):
        raise RuntimeError("workspace backend is not configured")

    content = {
        "schema": report.schema_id,
        "run_id": report.run_id,
        "status": report.status,
        "reason": report.reason,
        "completion_reason": report.completion_reason,
        "events_path": report.events_path,
        "artifact_refs": list(report.artifacts or []),
        "tool_call_count": len(report.tool_calls or []),
    }
    summary = _sanitize_text(
        f"NodeReport {report.run_id}: status={report.status}; "
        f"events={report.events_path}; artifacts={len(report.artifacts or [])}"
    )
    ref = await workspace.put(
        content,
        collection=str(collection),
        kind="node_report_summary",
        summary=summary,
        meta={"source": "capability-runtime", "schema": report.schema_id},
    )
    return _record_ref_from_value(ref, default_collection=str(collection), default_kind="node_report_summary")


def _extract_items(raw_pack: Any) -> list[Any]:
    """从多种 context pack 形态中提取 item 列表。"""

    if isinstance(raw_pack, dict):
        for key in ("items", "records", "context", "refs"):
            value = raw_pack.get(key)
            if isinstance(value, list):
                return list(value)
    value = getattr(raw_pack, "items", None)
    if isinstance(value, list):
        return list(value)
    return []


def _max_items_from_budget(budget: dict[str, Any] | None) -> int:
    """读取 context pack item 预算；默认保留 20 条。"""

    if not isinstance(budget, dict):
        return 20
    value = budget.get("max_items")
    if isinstance(value, int) and value >= 0:
        return value
    return 20


def _record_ref_from_value(
    value: Any,
    *,
    default_collection: str = "default",
    default_kind: str | None = None,
) -> RuntimeContextRecordRef:
    """把上游 record/ref 对象归一为 RuntimeContextRecordRef。"""

    if isinstance(value, dict):
        raw_id = value.get("id") or value.get("record_id") or value.get("path") or ""
        collection = value.get("collection") or default_collection
        kind = value.get("kind") or default_kind
        summary = value.get("summary") or value.get("title")
    else:
        raw_id = getattr(value, "id", None) or getattr(value, "record_id", None) or getattr(value, "path", None) or ""
        collection = getattr(value, "collection", None) or default_collection
        kind = getattr(value, "kind", None) or default_kind
        summary = getattr(value, "summary", None) or getattr(value, "title", None)
    return RuntimeContextRecordRef(
        id=_sanitize_text(str(raw_id or "")) or "unknown",
        collection=_sanitize_text(str(collection or default_collection)) or default_collection,
        kind=_sanitize_text(str(kind)) if kind is not None else None,
        summary=_sanitize_text(str(summary)) if summary is not None else None,
    )


def _sanitize_text(value: str) -> str:
    """脱敏自然语言摘要，避免写入密钥、Authorization 或 provider request 原文。"""

    text = _SENSITIVE_INLINE_RE.sub("[REDACTED]", str(value))
    text = _SENSITIVE_KEY_RE.sub("[REDACTED]", text)
    return text[:500]


__all__ = [
    "RuntimeContextRecordRef",
    "RuntimeRecallContextPack",
    "build_recall_context_pack",
    "write_node_report_summary",
]
