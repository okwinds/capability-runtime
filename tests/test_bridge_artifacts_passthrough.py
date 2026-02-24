from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from agent_sdk.core.contracts import AgentEvent

from agently_skills_runtime.config import RuntimeConfig
from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.protocol.capability import CapabilityKind, CapabilitySpec, CapabilityStatus
from agently_skills_runtime.protocol.context import ExecutionContext
from agently_skills_runtime.runtime import Runtime


class _FakeAgent:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    async def run_stream_async(
        self, task: str, *, run_id: Optional[str] = None, initial_history: Optional[List[Dict[str, Any]]] = None
    ) -> AsyncIterator[AgentEvent]:
        yield AgentEvent(type="run_started", timestamp="2026-02-24T00:00:00Z", run_id=run_id or "r1", payload={})
        yield AgentEvent(
            type="run_completed",
            timestamp="2026-02-24T00:00:01Z",
            run_id=run_id or "r1",
            payload={"final_output": "ok", "wal_locator": "wal.jsonl", "artifacts": ["handoff-1.md"]},
        )


@pytest.mark.asyncio
async def test_run_async_passes_report_artifacts_to_node_result(monkeypatch, tmp_path: Path) -> None:
    """
    回归护栏：CapabilityResult.artifacts 必须透传 NodeReport.artifacts（证据链对齐）。
    """

    monkeypatch.setattr("agent_sdk.core.agent.Agent", _FakeAgent)
    rt = Runtime(RuntimeConfig(mode="sdk_native", workspace_root=tmp_path, preflight_mode="off"))
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))

    out = await rt.run("A", context=ExecutionContext(run_id="r1"))
    assert out.status == CapabilityStatus.SUCCESS
    assert out.node_report is not None
    assert out.node_report.artifacts == ["handoff-1.md"]
    assert out.artifacts == ["handoff-1.md"]
