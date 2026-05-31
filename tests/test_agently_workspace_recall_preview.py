from __future__ import annotations

from typing import Any

import pytest

from capability_runtime.types import NodeReport


class _FakeWorkspace:
    """记录 adapter 调用的最小 Workspace 替身。"""

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
    """Slice F happy/edge：Workspace context 只转为中立 pack，摘要脱敏并尊重 budget。"""

    from capability_runtime.context_pack import RuntimeRecallContextPack, build_recall_context_pack

    workspace = _FakeWorkspace(
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

    pack = await build_recall_context_pack(workspace, goal="continue session", budget={"max_items": 1})

    assert isinstance(pack, RuntimeRecallContextPack)
    assert pack.goal == "continue session"
    assert len(pack.items) == 1
    assert pack.items[0].id == "rec-1"
    assert pack.items[0].collection == "notes"
    assert pack.omitted_count == 1
    dumped = str((pack.goal, pack.items, pack.diagnostics))
    assert "SECRET_TOKEN" not in dumped
    assert "Authorization" not in dumped
    assert "Workspace" not in dumped
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
        "code": "WORKSPACE_BACKEND_UNAVAILABLE",
        "message": "workspace backend is not configured",
    }


@pytest.mark.asyncio
async def test_node_report_summary_written_to_workspace_uses_sanitized_reference_only() -> None:
    """Slice F evidence write：写入 Workspace 的只能是 NodeReport 摘要，不含原始正文。"""

    from capability_runtime.context_pack import write_node_report_summary

    workspace = _FakeWorkspace()
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

    ref = await write_node_report_summary(workspace, report, collection="runtime_evidence")

    assert ref.id == "rec-written"
    assert ref.collection == "runtime_evidence"
    assert ref.kind == "node_report_summary"
    assert workspace.put_calls
    dumped = repr(workspace.put_calls)
    assert "run-secret" in dumped
    assert "wal://run-secret" in dumped
    assert "artifact://safe-ref" in dumped
    assert "SECRET_KEY" not in dumped
    assert "Bearer SECRET" not in dumped
    assert "provider_request" not in dumped
