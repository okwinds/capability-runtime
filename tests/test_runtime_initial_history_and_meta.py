from pathlib import Path
from types import MappingProxyType

import pytest

from skills_runtime.core.contracts import AgentEvent

from capability_runtime.config import RuntimeConfig
from capability_runtime.protocol.agent import AgentSpec
from capability_runtime.protocol.capability import CapabilityKind, CapabilitySpec
from capability_runtime.protocol.context import ExecutionContext
from capability_runtime.runtime import Runtime


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
    monkeypatch.setattr("skills_runtime.core.agent.Agent", lambda **_: _FakeAgent(events=[]))
    rt = Runtime(RuntimeConfig(mode="sdk_native", workspace_root=Path("."), preflight_mode="off"))
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    return rt


@pytest.mark.asyncio
async def test_run_async_passes_initial_history_to_sdk_agent(monkeypatch):
    fake_events = [
        AgentEvent(type="run_started", timestamp="2026-02-10T00:00:00Z", run_id="r1", payload={}),
        AgentEvent(
            type="run_completed",
            timestamp="2026-02-10T00:00:01Z",
            run_id="r1",
            payload={"final_output": "ok", "wal_locator": "wal.jsonl"},
        ),
    ]
    fake_agent = _FakeAgent(events=fake_events)
    monkeypatch.setattr("skills_runtime.core.agent.Agent", lambda **_: fake_agent)

    rt = Runtime(RuntimeConfig(mode="sdk_native", workspace_root=Path("."), preflight_mode="off"))
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))

    hist = [{"role": "user", "content": "hello"}]
    ctx = ExecutionContext(run_id="r1", bag=MappingProxyType({"__host_meta__": {"initial_history": hist}}))
    out = await rt.run("A", context=ctx)
    assert out.output == "ok"
    assert fake_agent.last_initial_history == hist
    assert out.node_report is not None
    assert out.node_report.meta["initial_history_injected"] is True


@pytest.mark.asyncio
async def test_run_async_injects_session_and_turn_id_into_node_report_meta(monkeypatch):
    fake_events = [
        AgentEvent(type="run_started", timestamp="2026-02-10T00:00:00Z", run_id="r1", payload={}),
        AgentEvent(
            type="run_completed",
            timestamp="2026-02-10T00:00:01Z",
            run_id="r1",
            payload={"final_output": "ok", "wal_locator": "wal.jsonl"},
        ),
    ]
    fake_agent = _FakeAgent(events=fake_events)
    monkeypatch.setattr("skills_runtime.core.agent.Agent", lambda **_: fake_agent)

    rt = Runtime(RuntimeConfig(mode="sdk_native", workspace_root=Path("."), preflight_mode="off"))
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))

    ctx = ExecutionContext(
        run_id="r1",
        bag=MappingProxyType({"__host_meta__": {"session_id": "SID", "host_turn_id": "TID"}}),
    )
    out = await rt.run("A", context=ctx)
    assert out.node_report is not None
    assert out.node_report.meta["session_id"] == "SID"
    assert out.node_report.meta["host_turn_id"] == "TID"


@pytest.mark.asyncio
async def test_run_async_records_prompt_evidence_without_plaintext(monkeypatch, tmp_path):
    fake_events = [
        AgentEvent(type="run_started", timestamp="2026-02-10T00:00:00Z", run_id="r1", payload={}),
        AgentEvent(
            type="run_completed",
            timestamp="2026-02-10T00:00:01Z",
            run_id="r1",
            payload={"final_output": "ok", "wal_locator": "wal.jsonl"},
        ),
    ]
    fake_agent = _FakeAgent(events=fake_events)
    monkeypatch.setattr("skills_runtime.core.agent.Agent", lambda **_: fake_agent)

    rt = Runtime(RuntimeConfig(mode="sdk_native", workspace_root=tmp_path, preflight_mode="off"))
    rt.register(
        AgentSpec(
            base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
            prompt_render_mode="direct_task_text",
            prompt_profile="generation_direct",
        )
    )

    secret_prompt = "SECRET PROMPT SHOULD NOT BE IN NODE REPORT"
    out = await rt.run(
        "A",
        input={
            "_runtime_prompt": {
                "task_text": secret_prompt,
                "trace": {
                    "prompt_hash": "sha256:" + "d" * 64,
                    "composer_version": "composer@3",
                },
            }
        },
        context=ExecutionContext(run_id="r1"),
    )

    assert fake_agent.last_task == secret_prompt
    assert out.node_report is not None
    assert out.node_report.meta["prompt_render_mode"] == "direct_task_text"
    assert out.node_report.meta["prompt_profile"] == "generation_direct"
    assert out.node_report.meta["prompt_hash"] == "sha256:" + "d" * 64
    assert out.node_report.meta["prompt_composer_version"] == "composer@3"
    assert secret_prompt not in out.node_report.model_dump_json()
