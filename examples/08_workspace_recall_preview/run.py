from __future__ import annotations

"""Recall context pack preview（离线 deterministic）。"""

import asyncio
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
for path in (REPO_ROOT, SRC_ROOT):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from capability_runtime import (
    NodeReport,
    RuntimeContextRecordRef,
    RuntimeRecallContextPack,
    build_recall_context_pack,
    write_node_report_summary,
)


class ExampleRecallBackend:
    """最小 RuntimeRecallBackend；只返回 refs，不作为 WAL。"""

    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []

    async def build_context(self, **kwargs: Any) -> dict[str, Any]:
        _ = kwargs
        return {
            "items": [
                {
                    "id": "rec-incident",
                    "collection": "incident_notes",
                    "kind": "summary",
                    "summary": "Payment webhook latency resolved; duplicate checks running.",
                },
                {
                    "id": "rec-secret",
                    "collection": "incident_notes",
                    "kind": "summary",
                    "summary": "Authorization: Bearer SHOULD_NOT_APPEAR",
                },
            ]
        }

    async def put(self, content: Any, **kwargs: Any) -> dict[str, Any]:
        self.writes.append({"content": content, "kwargs": kwargs})
        return {
            "id": "node-report-summary",
            "collection": kwargs.get("collection", "runtime_evidence"),
            "kind": kwargs.get("kind"),
            "summary": kwargs.get("summary"),
        }


async def main() -> None:
    backend = ExampleRecallBackend()
    pack = await build_recall_context_pack(
        backend,
        goal="continue incident briefing",
        budget={"max_items": 1},
    )
    report = NodeReport(
        status="success",
        completion_reason="run_completed",
        run_id="run-example",
        events_path="wal://run-example",
        artifacts=["artifact://brief.md"],
    )
    ref = await write_node_report_summary(backend, report)

    assert isinstance(pack, RuntimeRecallContextPack)
    assert isinstance(ref, RuntimeContextRecordRef)

    print("=== 08_workspace_recall_preview ===")
    print(f"context_goal={pack.goal}")
    print(f"context_item_count={len(pack.items)}")
    print(f"context_omitted_count={pack.omitted_count}")
    print(f"context_ref={pack.items[0].id if pack.items else None}")
    print(f"node_report_ref={ref.id}")
    print(f"raw_recall_backend_is_wal=false")


if __name__ == "__main__":
    asyncio.run(main())
