from pathlib import Path

import pytest

from agent_sdk.core.contracts import AgentEvent

import agently_skills_runtime.bridge as runtime_mod
from agently_skills_runtime.bridge import AgentlySkillsRuntime, AgentlySkillsRuntimeConfig


class _FakeRequester:
    def generate_request_data(self):
        return type(
            "Req",
            (),
            {"data": {"messages": []}, "request_options": {}, "stream": True, "headers": {}, "client_options": {}, "request_url": "x"},
        )()

    async def request_model(self, request_data):
        yield ("message", "[DONE]")


def _patch_requester_factory(monkeypatch):
    def fake_build(*, agently_agent):
        return lambda: _FakeRequester()

    monkeypatch.setattr(runtime_mod, "build_openai_compatible_requester_factory", fake_build)


class _FakeAgent:
    def __init__(self, *, events):
        self._events = list(events)

    async def run_stream_async(self, task, *, run_id=None, initial_history=None):
        for ev in self._events:
            yield ev


class _Hook:
    def __init__(self):
        self.called = []

    def before_preflight(self, context):
        self.called.append(("before_preflight", context.get("run_id")))

    def after_preflight(self, context, issues):
        self.called.append(("after_preflight", len(list(issues or []))))

    def before_run(self, context):
        self.called.append(("before_run", context.get("run_id")))

    def before_engine_start_turn(self, context):
        self.called.append(("before_engine_start_turn", context.get("turn_id")))

    def after_engine_event(self, context, event):
        self.called.append(("after_engine_event", event.type))

    def before_return_result(self, context, node_result):
        self.called.append(("before_return_result", node_result.node_report.status))

    def on_error(self, context, error):
        self.called.append(("on_error", type(error).__name__))


class _FailingSchemaGate:
    def validate(self, *, final_output, node_report, context):
        return {
            "mode": "warn",
            "ok": False,
            "schema_id": "demo.schema.v1",
            "normalized_payload": None,
            "errors": [{"path": "$.x", "kind": "missing", "message": "x is required"}],
        }


class _SchemaGateWithNormalizedPayload:
    def validate(self, *, final_output, node_report, context):
        return {
            "mode": "warn",
            "ok": True,
            "schema_id": "demo.schema.v1",
            "normalized_payload": {"a": 1, "b": "x"},
            "errors": [],
        }


def _mk_runtime(monkeypatch, *, hooks=None, schema_gate=None, schema_gate_mode="off"):
    _patch_requester_factory(monkeypatch)
    cfg = AgentlySkillsRuntimeConfig(
        workspace_root=Path("."),
        config_paths=[],
        preflight_mode="off",
        upstream_verification_mode="off",
    )
    return AgentlySkillsRuntime(
        agently_agent=object(),
        config=cfg,
        hooks=hooks,
        schema_gate=schema_gate,
        schema_gate_mode=schema_gate_mode,
    )


@pytest.mark.asyncio
async def test_hooks_are_called_and_trace_is_recorded(monkeypatch):
    hook = _Hook()
    rt = _mk_runtime(monkeypatch, hooks=[hook])

    fake_events = [
        AgentEvent(type="run_started", ts="2026-02-10T00:00:00Z", run_id="r1", payload={}),
        AgentEvent(type="skill_injected", ts="2026-02-10T00:00:00Z", run_id="r1", payload={"skill_name": "a.b"}),
        AgentEvent(type="run_completed", ts="2026-02-10T00:00:01Z", run_id="r1", payload={"final_output": "ok", "events_path": "wal.jsonl"}),
    ]
    monkeypatch.setattr(rt, "_get_or_create_agent", lambda: _FakeAgent(events=fake_events))

    out = await rt.run_async("hi")

    assert out.node_report.status == "success"
    assert ("before_preflight", None) in hook.called
    assert any(x[0] == "after_preflight" for x in hook.called)
    assert ("before_run", "r1") in hook.called
    assert any(x[0] == "after_engine_event" for x in hook.called)
    assert any(x[0] == "before_return_result" for x in hook.called)

    trace = out.node_report.meta.get("extension_trace", [])
    assert isinstance(trace, list)
    assert any(item.get("name") == "before_run" for item in trace)


@pytest.mark.asyncio
async def test_before_engine_start_turn_is_called_once(monkeypatch):
    hook = _Hook()
    rt = _mk_runtime(monkeypatch, hooks=[hook])

    fake_events = [
        AgentEvent(type="run_started", ts="2026-02-10T00:00:00Z", run_id="r1", turn_id="t1", payload={}),
        AgentEvent(type="run_completed", ts="2026-02-10T00:00:01Z", run_id="r1", turn_id="t1", payload={"final_output": "ok", "events_path": "wal.jsonl"}),
    ]
    monkeypatch.setattr(rt, "_get_or_create_agent", lambda: _FakeAgent(events=fake_events))

    out = await rt.run_async("hi")
    assert out.node_report.status == "success"
    assert ("before_engine_start_turn", "t1") in hook.called


@pytest.mark.asyncio
async def test_on_error_hook_is_called_when_agent_stream_raises(monkeypatch):
    hook = _Hook()
    rt = _mk_runtime(monkeypatch, hooks=[hook])

    class _BoomAgent:
        async def run_stream_async(self, task, *, run_id=None, initial_history=None):
            yield AgentEvent(type="run_started", ts="2026-02-10T00:00:00Z", run_id="r1", payload={})
            raise RuntimeError("boom")

    monkeypatch.setattr(rt, "_get_or_create_agent", lambda: _BoomAgent())

    out = await rt.run_async("hi")
    assert out.node_report.status == "failed"
    assert any(x[0] == "on_error" for x in hook.called)


@pytest.mark.asyncio
async def test_schema_gate_warn_records_meta_but_does_not_override_status(monkeypatch):
    rt = _mk_runtime(monkeypatch, schema_gate=_FailingSchemaGate(), schema_gate_mode="warn")

    fake_events = [
        AgentEvent(type="run_started", ts="2026-02-10T00:00:00Z", run_id="r1", payload={}),
        AgentEvent(type="run_completed", ts="2026-02-10T00:00:01Z", run_id="r1", payload={"final_output": "ok", "events_path": "wal.jsonl"}),
    ]
    monkeypatch.setattr(rt, "_get_or_create_agent", lambda: _FakeAgent(events=fake_events))

    out = await rt.run_async("hi")
    assert out.node_report.status == "success"
    sg = out.node_report.meta.get("schema_gate")
    assert sg is not None
    assert sg["mode"] == "warn"
    assert sg["ok"] is False


@pytest.mark.asyncio
async def test_schema_gate_error_overrides_status_to_failed(monkeypatch):
    rt = _mk_runtime(monkeypatch, schema_gate=_FailingSchemaGate(), schema_gate_mode="error")

    fake_events = [
        AgentEvent(type="run_started", ts="2026-02-10T00:00:00Z", run_id="r1", payload={}),
        AgentEvent(type="run_completed", ts="2026-02-10T00:00:01Z", run_id="r1", payload={"final_output": "ok", "events_path": "wal.jsonl"}),
    ]
    monkeypatch.setattr(rt, "_get_or_create_agent", lambda: _FakeAgent(events=fake_events))

    out = await rt.run_async("hi")
    assert out.node_report.status == "failed"
    assert out.node_report.reason == "schema_validation_error"
    assert out.node_report.meta.get("schema_gate_overrode_status") is True


@pytest.mark.asyncio
async def test_schema_gate_records_normalized_payload_digest_only(monkeypatch):
    rt = _mk_runtime(monkeypatch, schema_gate=_SchemaGateWithNormalizedPayload(), schema_gate_mode="warn")

    fake_events = [
        AgentEvent(type="run_started", ts="2026-02-10T00:00:00Z", run_id="r1", payload={}),
        AgentEvent(type="run_completed", ts="2026-02-10T00:00:01Z", run_id="r1", payload={"final_output": "ok", "events_path": "wal.jsonl"}),
    ]
    monkeypatch.setattr(rt, "_get_or_create_agent", lambda: _FakeAgent(events=fake_events))

    out = await rt.run_async("hi")
    sg = out.node_report.meta.get("schema_gate") or {}
    assert sg.get("ok") is True
    assert "normalized_payload_sha256" in sg
    assert "normalized_payload_bytes" in sg
    assert "normalized_payload_top_keys" in sg
    assert "normalized_payload" not in sg
