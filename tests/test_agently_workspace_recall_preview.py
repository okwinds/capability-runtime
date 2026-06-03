from __future__ import annotations

from typing import Any

import pytest

from capability_runtime.types import NodeReport


class _FakeRecallBackend:
    """记录 adapter 调用的最小 RuntimeRecallBackend 替身。"""

    def __init__(self, context: dict[str, Any] | None = None) -> None:
        self.context = context or {}
        self.put_calls: list[dict[str, Any]] = []

    async def build_context(self, **kwargs: Any) -> dict[str, Any]:
        self.last_build_context_kwargs = kwargs
        return dict(self.context)

    async def put(self, record_or_content: Any, **kwargs: Any) -> dict[str, Any]:
        self.put_calls.append({"content": record_or_content, "kwargs": kwargs})
        return {
            "id": "rec-written",
            "collection": kwargs.get("collection", "runtime_evidence"),
            "kind": kwargs.get("kind"),
            "summary": kwargs.get("summary"),
        }


@pytest.mark.asyncio
async def test_workspace_build_context_becomes_neutral_context_pack_and_redacts_secrets() -> None:
    """Slice F happy/edge：recall backend context 只转为中立 pack，摘要脱敏并尊重 budget。"""

    from capability_runtime.context_pack import RuntimeRecallBackend, RuntimeRecallContextPack, build_recall_context_pack

    backend = _FakeRecallBackend(
        {
            "items": [
                {
                    "id": "rec-1",
                    "collection": "notes",
                    "kind": "summary",
                    "summary": "useful context Authorization: Bearer SECRET_TOKEN",
                },
                {
                    "id": "rec-2",
                    "collection": "notes",
                    "kind": "summary",
                    "summary": "second item should be omitted",
                },
            ]
        }
    )

    assert isinstance(backend, RuntimeRecallBackend)
    pack = await build_recall_context_pack(backend, goal="continue session", budget={"max_items": 1})

    assert isinstance(pack, RuntimeRecallContextPack)
    assert pack.goal == "continue session"
    assert len(pack.items) == 1
    assert pack.items[0].id == "rec-1"
    assert pack.items[0].collection == "notes"
    assert pack.omitted_count == 1
    dumped = str((pack.goal, pack.items, pack.diagnostics))
    assert "SECRET_TOKEN" not in dumped
    assert "Authorization" not in dumped
    assert "Recall" not in dumped


@pytest.mark.asyncio
async def test_workspace_context_preview_degrades_stably_when_backend_unavailable() -> None:
    """Slice F error path：backend 不可用时返回稳定 degraded diagnostics。"""

    from capability_runtime.context_pack import build_recall_context_pack

    pack = await build_recall_context_pack(None, goal="continue session")

    assert pack.goal == "continue session"
    assert pack.items == ()
    assert pack.omitted_count == 0
    assert pack.diagnostics == {
        "degraded": True,
        "code": "RECALL_BACKEND_UNAVAILABLE",
        "message": "recall backend is not configured",
    }


@pytest.mark.asyncio
async def test_node_report_summary_written_to_workspace_uses_sanitized_reference_only() -> None:
    """Slice F evidence write：写入 recall backend 的只能是 NodeReport 摘要，不含原始正文。"""

    from capability_runtime.context_pack import write_node_report_summary

    backend = _FakeRecallBackend()
    report = NodeReport(
        status="success",
        completion_reason="run_completed",
        run_id="run-secret",
        events_path="wal://run-secret",
        artifacts=["artifact://safe-ref"],
        meta={
            "final_message": "raw provider output with api_key=SECRET_KEY",
            "provider_request": {"headers": {"Authorization": "Bearer SECRET"}},
        },
    )

    ref = await write_node_report_summary(backend, report, collection="runtime_evidence")

    assert ref.id == "rec-written"
    assert ref.collection == "runtime_evidence"
    assert ref.kind == "node_report_summary"
    assert backend.put_calls
    dumped = repr(backend.put_calls)
    assert "run-secret" in dumped
    assert "wal://run-secret" not in dumped
    assert "artifact://safe-ref" not in dumped
    assert "events_path_hash" in dumped
    assert "artifact_ref_count" in dumped
    assert "SECRET_KEY" not in dumped
    assert "Bearer SECRET" not in dumped
    assert "provider_request" not in dumped


def test_context_record_ref_preserves_identifier_fields_but_redacts_summary() -> None:
    """record id/collection 是稳定引用，不能因关键词脱敏被改写。"""

    from capability_runtime.context_pack import _record_ref_from_value

    ref = _record_ref_from_value(
        {
            "id": "token-record-1",
            "collection": "secret-notes",
            "kind": "credential-summary",
            "summary": "Authorization: Bearer SHOULD_NOT_LEAK",
        }
    )

    assert ref.id == "token-record-1"
    assert ref.collection == "secret-notes"
    assert ref.kind == "credential-summary"
    assert ref.summary is not None
    assert "SHOULD_NOT_LEAK" not in ref.summary
    assert "Authorization" not in ref.summary


def test_context_record_ref_hashes_raw_path_locator_when_id_is_missing() -> None:
    """Recall backend path / WAL / signed URL 不能作为 raw record id 泄露。"""

    from capability_runtime.context_pack import _record_ref_from_value

    ref = _record_ref_from_value(
        {
            "path": "wal://secret-run/private.jsonl?token=SHOULD_NOT_LEAK",
            "collection": "runtime_evidence",
            "summary": "safe summary",
        }
    )

    assert ref.id.startswith("opaque-ref:sha256:")
    assert "wal://secret-run" not in ref.id
    assert "SHOULD_NOT_LEAK" not in ref.id


def test_context_record_ref_hashes_locator_like_id_values() -> None:
    """Recall backend 若把 locator 放进 id/record_id，也不能原样进入 context pack。"""

    from types import SimpleNamespace

    from capability_runtime.context_pack import _record_ref_from_value

    dict_ref = _record_ref_from_value(
        {
            "id": "https://provider.example/private/context.json?token=SHOULD_NOT_LEAK",
            "collection": "runtime_evidence",
        }
    )
    object_ref = _record_ref_from_value(
        SimpleNamespace(
            record_id="/var/private/wal/run-secret.jsonl",
            collection="runtime_evidence",
        )
    )

    assert dict_ref.id.startswith("opaque-ref:sha256:")
    assert object_ref.id.startswith("opaque-ref:sha256:")
    dumped = repr((dict_ref, object_ref))
    assert "provider.example/private" not in dumped
    assert "SHOULD_NOT_LEAK" not in dumped
    assert "/var/private/wal" not in dumped
