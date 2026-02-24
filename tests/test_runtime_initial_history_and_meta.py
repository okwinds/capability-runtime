from pathlib import Path

import pytest

from agent_sdk.core.contracts import AgentEvent

from agently_skills_runtime.config import RuntimeConfig
from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.protocol.capability import CapabilityKind, CapabilitySpec
from agently_skills_runtime.protocol.context import ExecutionContext
from agently_skills_runtime.runtime import Runtime


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
    monkeypatch.setattr("agent_sdk.core.agent.Agent", lambda **_: _FakeAgent(events=[]))
    rt = Runtime(RuntimeConfig(mode="sdk_native", workspace_root=Path("."), preflight_mode="off"))
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    return rt


@pytest.mark.asyncio
async def test_run_async_passes_initial_history_to_sdk_agent(monkeypatch):
    fake_events = [
        AgentEvent(type="run_started", ts="2026-02-10T00:00:00Z", run_id="r1", payload={}),
        AgentEvent(type="run_completed", ts="2026-02-10T00:00:01Z", run_id="r1", payload={"final_output": "ok", "events_path": "wal.jsonl"}),
    ]
    fake_agent = _FakeAgent(events=fake_events)
    monkeypatch.setattr("agent_sdk.core.agent.Agent", lambda **_: fake_agent)

    rt = Runtime(RuntimeConfig(mode="sdk_native", workspace_root=Path("."), preflight_mode="off"))
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))

    hist = [{"role": "user", "content": "hello"}]
    ctx = ExecutionContext(run_id="r1", bag={"__host_meta__": {"initial_history": hist}})
    out = await rt.run("A", context=ctx)
    assert out.output == "ok"
    assert fake_agent.last_initial_history == hist
    assert out.node_report is not None
    assert out.node_report.meta["initial_history_injected"] is True


@pytest.mark.asyncio
async def test_run_async_injects_session_and_turn_id_into_node_report_meta(monkeypatch):
    fake_events = [
        AgentEvent(type="run_started", ts="2026-02-10T00:00:00Z", run_id="r1", payload={}),
        AgentEvent(type="run_completed", ts="2026-02-10T00:00:01Z", run_id="r1", payload={"final_output": "ok", "events_path": "wal.jsonl"}),
    ]
    fake_agent = _FakeAgent(events=fake_events)
    monkeypatch.setattr("agent_sdk.core.agent.Agent", lambda **_: fake_agent)

    rt = Runtime(RuntimeConfig(mode="sdk_native", workspace_root=Path("."), preflight_mode="off"))
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))

    ctx = ExecutionContext(
        run_id="r1",
        bag={"__host_meta__": {"session_id": "SID", "host_turn_id": "TID"}},
    )
    out = await rt.run("A", context=ctx)
    assert out.node_report is not None
    assert out.node_report.meta["session_id"] == "SID"
    assert out.node_report.meta["host_turn_id"] == "TID"
