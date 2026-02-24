from __future__ import annotations

from pathlib import Path

import pytest

from typing import Any, AsyncIterator, Dict, List, Optional

from agent_sdk.core.contracts import AgentEvent
from agent_sdk.core.errors import FrameworkIssue

from agently_skills_runtime.config import RuntimeConfig
from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.protocol.capability import CapabilityKind, CapabilitySpec
from agently_skills_runtime.protocol.context import ExecutionContext
from agently_skills_runtime.runtime import Runtime


class _FakeAgent:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    async def run_stream_async(
        self,
        task: str,
        *,
        run_id: Optional[str] = None,
        initial_history: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[AgentEvent]:
        _ = task
        _ = initial_history
        yield AgentEvent(type="run_started", ts="2026-02-12T00:00:00Z", run_id=run_id or "r1", payload={})
        yield AgentEvent(
            type="run_completed",
            ts="2026-02-12T00:00:01Z",
            run_id=run_id or "r1",
            payload={"final_output": "ok", "events_path": "e.jsonl"},
        )


def _mk_runtime(monkeypatch: pytest.MonkeyPatch, *, preflight_mode: str, output_validation_mode: str = "off", output_validator=None) -> Runtime:
    monkeypatch.setattr("agent_sdk.core.agent.Agent", _FakeAgent)
    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=Path("."),
            preflight_mode=preflight_mode,  # type: ignore[arg-type]
            output_validation_mode=output_validation_mode,  # type: ignore[arg-type]
            output_validator=output_validator,
        )
    )
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    return rt


@pytest.mark.asyncio
async def test_engine_name_is_fixed_when_preflight_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    契约护栏：无论 Bridge 走哪条 fail-closed 分支，NodeReport.engine.name 必须稳定。

    本用例覆盖：preflight gate fail-closed（run_async 在执行引擎前返回）。
    """

    rt = _mk_runtime(monkeypatch, preflight_mode="error")
    monkeypatch.setattr(rt, "_preflight", lambda: [FrameworkIssue(code="SKILL_PREFLIGHT_FAILED", message="x", details={})])

    out = await rt.run("A", context=ExecutionContext(run_id="rid-preflight"))
    assert out.node_report is not None
    assert out.node_report.engine.get("name") == "skills-runtime-sdk-python"
    assert out.node_report.engine.get("module") == "agent_sdk"


@pytest.mark.asyncio
async def test_engine_name_is_fixed_when_output_validation_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    契约护栏：output validator 覆盖为 failed 时 engine.name 也必须稳定。
    """

    def validator(*, final_output: str, node_report, context: Dict[str, Any]) -> Dict[str, Any]:
        _ = final_output
        _ = node_report
        _ = context
        return {"ok": False, "schema_id": "demo.schema.v1", "errors": [{"path": "$.x", "kind": "missing", "message": "x is required"}]}

    rt = _mk_runtime(monkeypatch, preflight_mode="off", output_validation_mode="error", output_validator=validator)
    out = await rt.run("A", context=ExecutionContext(run_id="rid-ov"))
    assert out.node_report is not None
    assert out.node_report.engine.get("name") == "skills-runtime-sdk-python"
    assert out.node_report.engine.get("module") == "agent_sdk"
