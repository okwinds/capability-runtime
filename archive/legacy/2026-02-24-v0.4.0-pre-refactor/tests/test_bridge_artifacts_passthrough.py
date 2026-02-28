from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from agent_sdk.core.contracts import AgentEvent

from capability_runtime.bridge import Runtime, RuntimeConfig


class _FakeAgent:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    async def run_stream_async(
        self, task: str, *, run_id: Optional[str] = None, initial_history: Optional[List[Dict[str, Any]]] = None
    ) -> AsyncIterator[AgentEvent]:
        yield AgentEvent(type="run_started", ts="2026-02-24T00:00:00Z", run_id=run_id or "r1", payload={})
        yield AgentEvent(
            type="run_completed",
            ts="2026-02-24T00:00:01Z",
            run_id=run_id or "r1",
            payload={"final_output": "ok", "events_path": "wal.jsonl", "artifacts": ["handoff-1.md"]},
        )


@pytest.mark.asyncio
async def test_run_async_passes_report_artifacts_to_node_result(monkeypatch, tmp_path: Path) -> None:
    """
    回归护栏：NodeResult.artifacts 必须透传 NodeReport.artifacts（证据链对齐）。
    """

    cfg = RuntimeConfig(
        workspace_root=tmp_path,
        config_paths=[],
        backend_mode="sdk_openai_chat_completions",
        preflight_mode="off",
        upstream_verification_mode="off",
    )

    import capability_runtime.bridge as rt_mod

    monkeypatch.setattr(rt_mod, "Agent", _FakeAgent)

    rt = Runtime(agently_agent=object(), config=cfg)
    out = await rt.run_async("hello", run_id="r1")

    assert out.node_report.artifacts == ["handoff-1.md"]
    assert out.artifacts == ["handoff-1.md"]

