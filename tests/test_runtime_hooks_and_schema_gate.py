from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from skills_runtime.core.contracts import AgentEvent

from capability_runtime.config import RuntimeConfig
from capability_runtime.protocol.agent import AgentSpec
from capability_runtime.protocol.capability import (
    CapabilityKind,
    CapabilitySpec,
    CapabilityStatus,
)
from capability_runtime.protocol.context import ExecutionContext
from capability_runtime.runtime import Runtime


class _FakeAgent:
    """离线 fake SDK Agent：回放固定事件流。"""

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
        yield AgentEvent(type="run_started", timestamp="2026-02-10T00:00:00Z", run_id=run_id or "r1", payload={})
        yield AgentEvent(
            type="run_completed",
            timestamp="2026-02-10T00:00:01Z",
            run_id=run_id or "r1",
            payload={"final_output": "ok", "wal_locator": "wal.jsonl"},
        )


def _mk_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    on_event=None,
    output_validation_mode: str = "off",
    output_validator=None,
) -> Runtime:
    monkeypatch.setattr("skills_runtime.core.agent.Agent", _FakeAgent)
    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=Path("."),
            preflight_mode="off",
            on_event=on_event,
            output_validation_mode=output_validation_mode,  # type: ignore[arg-type]
            output_validator=output_validator,
        )
    )
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    return rt


@pytest.mark.asyncio
async def test_on_event_callback_is_called(monkeypatch: pytest.MonkeyPatch) -> None:
    called: List[str] = []

    def on_event(event: Any, ctx: Dict[str, Any]) -> None:
        called.append(f"{ctx.get('capability_id')}::{event.type}")

    rt = _mk_runtime(monkeypatch, on_event=on_event)
    out = await rt.run("A", context=ExecutionContext(run_id="r-on-event"))
    assert out.status == CapabilityStatus.SUCCESS
    assert called == ["A::run_started", "A::run_completed"]


@pytest.mark.asyncio
async def test_output_validator_warn_records_meta_but_does_not_override_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def validator(*, final_output: str, node_report, context: Dict[str, Any]) -> Dict[str, Any]:
        _ = final_output
        _ = node_report
        assert context.get("capability_id") == "A"
        return {
            "ok": False,
            "schema_id": "demo.schema.v1",
            "errors": [{"path": "$.x", "kind": "missing", "message": "x is required"}],
        }

    rt = _mk_runtime(monkeypatch, output_validation_mode="warn", output_validator=validator)
    out = await rt.run("A", context=ExecutionContext(run_id="r-ov-warn"))
    assert out.node_report is not None
    assert out.node_report.status == "success"
    ov = out.node_report.meta.get("output_validation") or {}
    assert ov.get("mode") == "warn"
    assert ov.get("ok") is False
    assert ov.get("schema_id") == "demo.schema.v1"


@pytest.mark.asyncio
async def test_output_validator_error_overrides_status_to_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    def validator(*, final_output: str, node_report, context: Dict[str, Any]) -> Dict[str, Any]:
        _ = final_output
        _ = node_report
        _ = context
        return {"ok": False, "schema_id": "demo.schema.v1", "errors": [{"path": "$.x", "kind": "missing", "message": "x is required"}]}

    rt = _mk_runtime(monkeypatch, output_validation_mode="error", output_validator=validator)
    out = await rt.run("A", context=ExecutionContext(run_id="r-ov-error"))
    assert out.node_report is not None
    assert out.node_report.status == "failed"
    assert out.node_report.reason == "output_validation_error"
    assert out.node_report.meta.get("output_validation_overrode_status") is True


@pytest.mark.asyncio
async def test_output_validator_records_normalized_payload_digest_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def validator(*, final_output: str, node_report, context: Dict[str, Any]) -> Dict[str, Any]:
        _ = final_output
        _ = node_report
        _ = context
        return {"ok": True, "schema_id": "demo.schema.v1", "normalized_payload": {"a": 1, "b": "x"}, "errors": []}

    rt = _mk_runtime(monkeypatch, output_validation_mode="warn", output_validator=validator)
    out = await rt.run("A", context=ExecutionContext(run_id="r-ov-digest"))
    assert out.node_report is not None
    ov = out.node_report.meta.get("output_validation") or {}
    assert ov.get("ok") is True
    assert "normalized_payload_sha256" in ov
    assert "normalized_payload_bytes" in ov
    assert "normalized_payload_top_keys" in ov
    assert "normalized_payload" not in ov


@pytest.mark.asyncio
async def test_output_validator_internal_typeerror_is_reported_not_mistaken_for_signature_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def validator(*, final_output: str, node_report, context: Dict[str, Any]) -> Dict[str, Any]:
        _ = (final_output, node_report, context)
        raise TypeError("validator-bug")

    rt = _mk_runtime(monkeypatch, output_validation_mode="warn", output_validator=validator)
    out = await rt.run("A", context=ExecutionContext(run_id="r-ov-typeerror"))
    assert out.node_report is not None
    ov = out.node_report.meta.get("output_validation") or {}
    assert ov.get("ok") is False
    assert ov.get("error") == "validator_exception:TypeError"
