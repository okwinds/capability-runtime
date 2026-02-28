from pathlib import Path

import pytest

from agent_sdk.core.contracts import AgentEvent

import capability_runtime.runtime as runtime_mod
from capability_runtime.runtime import Runtime, RuntimeConfig


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
        self.last_initial_history = None
        self.last_run_id = None
        self.last_task = None

    async def run_stream_async(self, task, *, run_id=None, initial_history=None):
        self.last_task = task
        self.last_run_id = run_id
        self.last_initial_history = initial_history
        for ev in self._events:
            yield ev


def _mk_runtime(monkeypatch):
    _patch_requester_factory(monkeypatch)
    cfg = RuntimeConfig(
        workspace_root=Path("."),
        config_paths=[],
        preflight_mode="off",
    )
    return Runtime(agently_agent=object(), config=cfg)


@pytest.mark.asyncio
async def test_run_async_passes_initial_history_to_sdk_agent(monkeypatch):
    rt = _mk_runtime(monkeypatch)

    fake_events = [
        AgentEvent(type="run_started", ts="2026-02-10T00:00:00Z", run_id="r1", payload={}),
        AgentEvent(type="run_completed", ts="2026-02-10T00:00:01Z", run_id="r1", payload={"final_output": "ok", "events_path": "wal.jsonl"}),
    ]
    fake_agent = _FakeAgent(events=fake_events)
    monkeypatch.setattr(rt, "_get_or_create_agent", lambda: fake_agent)

    hist = [{"role": "user", "content": "hello"}]
    out = await rt.run_async("hi", initial_history=hist)
    assert out.final_output == "ok"
    assert fake_agent.last_initial_history == hist
    assert out.node_report.meta["initial_history_injected"] is True


@pytest.mark.asyncio
async def test_run_async_injects_session_and_turn_id_into_node_report_meta(monkeypatch):
    rt = _mk_runtime(monkeypatch)

    fake_events = [
        AgentEvent(type="run_started", ts="2026-02-10T00:00:00Z", run_id="r1", payload={}),
        AgentEvent(type="run_completed", ts="2026-02-10T00:00:01Z", run_id="r1", payload={"final_output": "ok", "events_path": "wal.jsonl"}),
    ]
    monkeypatch.setattr(rt, "_get_or_create_agent", lambda: _FakeAgent(events=fake_events))

    out = await rt.run_async("hi", session_id="SID", turn_id="TID")
    assert out.node_report.meta["session_id"] == "SID"
    assert out.node_report.meta["host_turn_id"] == "TID"

