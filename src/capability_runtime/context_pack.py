from __future__ import annotations

"""Neutral Runtime recall context pack contract and helpers."""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .types import NodeReport


_SENSITIVE_KEY_RE = re.compile(r"(authorization|api[_-]?key|secret|token|password|credential)", re.IGNORECASE)
_SENSITIVE_INLINE_RE = re.compile(
    r"(authorization\s*:\s*bearer\s+|api[_-]?key\s*[=:]\s*|token\s*[=:]\s*|secret\s*[=:]\s*)\S+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RuntimeContextRecordRef:
    """
    Runtime-side context record reference.

    Parameters:
    - id: stable record id or opaque locator hash
    - collection: source collection
    - kind: optional record kind
    - summary: redacted short summary
    """

    id: str
    collection: str
    kind: str | None = None
    summary: str | None = None


@dataclass(frozen=True)
class RuntimeRecallContextPack:
    """
    Runtime-side recall context pack.

    Parameters:
    - goal: context-building goal
    - items: neutral record refs
    - omitted_count: number of records omitted by budget
    - diagnostics: stable diagnostics without upstream workspace facades or raw provider requests
    """

    goal: str
    items: tuple[RuntimeContextRecordRef, ...]
    omitted_count: int = 0
    diagnostics: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class RuntimeRecallBackend(Protocol):
    """
    Runtime-owned recall backend protocol.

    Hosts may implement this protocol with any backend. An upstream Workspace is
    only one possible adapter behind the protocol and is not part of the stable
    downstream dependency surface.
    """

    async def build_context(
        self,
        *,
        goal: str,
        scope: dict[str, Any],
        budget: dict[str, Any],
        profile: str,
    ) -> Any:
        """Build raw context candidates."""

    async def put(
        self,
        record_or_content: Any,
        *,
        collection: str,
        kind: str,
        summary: str,
        meta: dict[str, Any],
    ) -> Any:
        """Write a redacted runtime evidence summary."""


async def build_recall_context_pack(
    backend: RuntimeRecallBackend | None,
    *,
    goal: str,
    scope: dict[str, Any] | None = None,
    budget: dict[str, Any] | None = None,
    profile: str = "auto",
) -> RuntimeRecallContextPack:
    """
    Read from a runtime recall backend and normalize to a neutral context pack.

    Parameters:
    - backend: host backend implementing `RuntimeRecallBackend`; None returns a degraded pack
    - goal: context-building goal
    - scope: optional retrieval scope
    - budget: optional budget, supports `max_items`
    - profile: backend profile name
    """

    if backend is None or not callable(getattr(backend, "build_context", None)):
        return RuntimeRecallContextPack(
            goal=str(goal),
            items=(),
            omitted_count=0,
            diagnostics={
                "degraded": True,
                "code": "RECALL_BACKEND_UNAVAILABLE",
                "message": "recall backend is not configured",
            },
        )

    try:
        raw_pack = await backend.build_context(
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
                "code": "RECALL_BUILD_CONTEXT_FAILED",
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
    backend: RuntimeRecallBackend | None,
    report: NodeReport,
    *,
    collection: str = "runtime_evidence",
) -> RuntimeContextRecordRef:
    """
    Write a minimal NodeReport summary into a runtime recall backend.

    Parameters:
    - backend: host backend implementing `RuntimeRecallBackend`
    - report: NodeReport truth-source summary
    - collection: target collection
    """

    if backend is None or not callable(getattr(backend, "put", None)):
        raise RuntimeError("recall backend is not configured")

    content = {
        "schema": report.schema_id,
        "run_id": report.run_id,
        "status": report.status,
        "reason": report.reason,
        "completion_reason": report.completion_reason,
        "events_path_hash": _hash_locator(report.events_path),
        "artifact_ref_count": len(report.artifacts or []),
        "artifact_ref_hashes": [_hash_locator(item) for item in list(report.artifacts or []) if isinstance(item, str)],
        "tool_call_count": len(report.tool_calls or []),
    }
    summary = _sanitize_text(
        f"NodeReport {report.run_id}: status={report.status}; "
        f"events_hash={content['events_path_hash']}; artifacts={len(report.artifacts or [])}"
    )
    ref = await backend.put(
        content,
        collection=str(collection),
        kind="node_report_summary",
        summary=summary,
        meta={"source": "capability-runtime", "schema": report.schema_id},
    )
    return _record_ref_from_value(ref, default_collection=str(collection), default_kind="node_report_summary")


def _extract_items(raw_pack: Any) -> list[Any]:
    """Extract item lists from common context pack shapes."""

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
    """Read the context pack item budget; default to 20 records."""

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
    """Normalize upstream-like record/ref values into RuntimeContextRecordRef."""

    if isinstance(value, dict):
        raw_id = value.get("id") or value.get("record_id") or ""
        raw_path = value.get("path")
        collection = value.get("collection") or default_collection
        kind = value.get("kind") or default_kind
        summary = value.get("summary") or value.get("title")
    else:
        raw_id = getattr(value, "id", None) or getattr(value, "record_id", None) or ""
        raw_path = getattr(value, "path", None)
        collection = getattr(value, "collection", None) or default_collection
        kind = getattr(value, "kind", None) or default_kind
        summary = getattr(value, "summary", None) or getattr(value, "title", None)
    if isinstance(raw_id, str) and _is_locator_like(raw_id):
        raw_id = "opaque-ref:" + _hash_locator(raw_id)
    elif not raw_id and isinstance(raw_path, str) and raw_path.strip():
        raw_id = "opaque-ref:" + _hash_locator(raw_path)
    return RuntimeContextRecordRef(
        id=_identifier_text(str(raw_id or "")) or "unknown",
        collection=_identifier_text(str(collection or default_collection)) or default_collection,
        kind=_identifier_text(str(kind)) if kind is not None else None,
        summary=_sanitize_text(str(summary)) if summary is not None else None,
    )


def _hash_locator(value: Any) -> str | None:
    """Hash locators irreversibly before storing them in recall evidence."""

    if not isinstance(value, str) or not value.strip():
        return None
    return "sha256:" + hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def _is_locator_like(value: Any) -> bool:
    """Detect WAL/path/signed-URL-like record ids that must be hashed."""

    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    return "://" in text or text.startswith(("/", "\\")) or "/" in text or "\\" in text or "?" in text


def _identifier_text(value: str) -> str:
    """Keep identifiers stable while trimming control characters and excessive length."""

    text = "".join(ch for ch in str(value) if ch.isprintable())
    return text[:500]


def _sanitize_text(value: str) -> str:
    """Redact natural-language summaries before writing recall evidence."""

    text = _SENSITIVE_INLINE_RE.sub("[REDACTED]", str(value))
    text = _SENSITIVE_KEY_RE.sub("[REDACTED]", text)
    return text[:500]


__all__ = [
    "RuntimeContextRecordRef",
    "RuntimeRecallBackend",
    "RuntimeRecallContextPack",
    "build_recall_context_pack",
    "write_node_report_summary",
]
