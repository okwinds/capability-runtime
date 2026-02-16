import asyncio
from pathlib import Path

import pytest

from agent_sdk.core.contracts import AgentEvent
from agent_sdk.core.errors import FrameworkError, FrameworkIssue

import agently_skills_runtime.runtime as runtime_mod
from agently_skills_runtime.runtime import (
    AgentlySkillsRuntime,
    AgentlySkillsRuntimeConfig,
    AgentlySkillsRuntimeConfig as RuntimeCfg,
)


class _FakeAgent:
    def __init__(self, events):
        self._events = list(events)

    async def run_stream_async(self, task, *, run_id=None, initial_history=None):
        for ev in self._events:
            yield ev


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


def _mk_runtime(monkeypatch, *, preflight_mode="error", config_paths=None):
    _patch_requester_factory(monkeypatch)
    cfg = AgentlySkillsRuntimeConfig(
        workspace_root=Path("."),
        config_paths=[Path(p) for p in (config_paths or [])],
        preflight_mode=preflight_mode,
    )
    # agently_agent is unused after patching requester_factory
    return AgentlySkillsRuntime(agently_agent=object(), config=cfg)


@pytest.mark.asyncio
async def test_run_async_preflight_error_returns_failed_node_report(monkeypatch):
    rt = _mk_runtime(monkeypatch, preflight_mode="error")
    monkeypatch.setattr(
        rt,
        "preflight",
        lambda: [FrameworkIssue(code="X", message="m", details={"path": "skills.scan.ttlSecs"})],
    )

    out = await rt.run_async("hi")
    assert out.node_report.status == "failed"
    assert out.node_report.reason == "skill_config_error"
    assert out.node_report.completion_reason == "preflight_failed"
    assert "preflight_issues" in out.node_report.meta


@pytest.mark.asyncio
async def test_run_async_preflight_warn_injects_meta(monkeypatch):
    rt = _mk_runtime(monkeypatch, preflight_mode="warn")
    monkeypatch.setattr(
        rt,
        "preflight",
        lambda: [FrameworkIssue(code="X", message="m", details={"path": "skills.scan.ttlSecs"})],
    )

    fake_events = [
        AgentEvent(type="run_started", ts="2026-02-10T00:00:00Z", run_id="r1", payload={}),
        AgentEvent(
            type="run_completed",
            ts="2026-02-10T00:00:01Z",
            run_id="r1",
            payload={"final_output": "ok", "events_path": "wal.jsonl"},
        ),
    ]
    monkeypatch.setattr(rt, "_get_or_create_agent", lambda: _FakeAgent(fake_events))

    out = await rt.run_async("hi")
    assert out.node_report.status == "success"
    assert out.node_report.meta["preflight_mode"] == "warn"
    assert out.node_report.meta["preflight_issues"][0]["code"] == "X"


@pytest.mark.asyncio
async def test_run_async_preflight_off_does_not_call_preflight(monkeypatch):
    rt = _mk_runtime(monkeypatch, preflight_mode="off")
    monkeypatch.setattr(rt, "preflight", lambda: (_ for _ in ()).throw(RuntimeError("should not call")))

    fake_events = [
        AgentEvent(type="run_started", ts="2026-02-10T00:00:00Z", run_id="r1", payload={}),
        AgentEvent(
            type="run_completed",
            ts="2026-02-10T00:00:01Z",
            run_id="r1",
            payload={"final_output": "ok", "events_path": "wal.jsonl"},
        ),
    ]
    monkeypatch.setattr(rt, "_get_or_create_agent", lambda: _FakeAgent(fake_events))

    out = await rt.run_async("hi")
    assert out.node_report.status == "success"


def test_preflight_or_raise_raises_framework_error(monkeypatch):
    rt = _mk_runtime(monkeypatch, preflight_mode="error")
    monkeypatch.setattr(
        rt,
        "preflight",
        lambda: [FrameworkIssue(code="X", message="m", details={"path": "skills.scan.ttlSecs"})],
    )
    with pytest.raises(FrameworkError) as ei:
        rt.preflight_or_raise()
    assert ei.value.code == "SKILL_PREFLIGHT_FAILED"


def test_preflight_or_raise_noop_when_no_issues(monkeypatch):
    rt = _mk_runtime(monkeypatch, preflight_mode="error")
    monkeypatch.setattr(rt, "preflight", lambda: [])
    rt.preflight_or_raise()


@pytest.mark.asyncio
async def test_run_sync_wrapper_works_outside_event_loop(monkeypatch):
    rt = _mk_runtime(monkeypatch, preflight_mode="off")
    fake_events = [
        AgentEvent(type="run_started", ts="2026-02-10T00:00:00Z", run_id="r1", payload={}),
        AgentEvent(
            type="run_completed",
            ts="2026-02-10T00:00:01Z",
            run_id="r1",
            payload={"final_output": "ok", "events_path": "wal.jsonl"},
        ),
    ]
    monkeypatch.setattr(rt, "_get_or_create_agent", lambda: _FakeAgent(fake_events))

    out = await asyncio.to_thread(rt.run, "hi")
    assert out.final_output == "ok"


@pytest.mark.asyncio
async def test_run_sync_wrapper_raises_inside_event_loop(monkeypatch):
    rt = _mk_runtime(monkeypatch, preflight_mode="off")
    with pytest.raises(RuntimeError, match="running event loop"):
        rt.run("hi")


def test_preflight_detects_legacy_roots_overlay(tmp_path, monkeypatch):
    overlay = tmp_path / "bad.yaml"
    overlay.write_text("skills:\n  roots:\n    - /tmp\n", encoding="utf-8")
    rt = _mk_runtime(monkeypatch, preflight_mode="off", config_paths=[overlay])
    issues = rt.preflight()
    assert any(i.code == "SKILL_CONFIG_LEGACY_ROOTS_UNSUPPORTED" for i in issues)


def test_preflight_warn_mode_does_not_block_on_unknown_scan_option(tmp_path, monkeypatch):
    overlay = tmp_path / "warn.yaml"
    overlay.write_text("skills:\n  scan:\n    ttlSecs: 10\n", encoding="utf-8")
    rt = _mk_runtime(monkeypatch, preflight_mode="warn", config_paths=[overlay])
    issues = rt.preflight()
    assert any(i.code == "SKILL_CONFIG_UNKNOWN_SCAN_OPTION" for i in issues)


@pytest.mark.asyncio
async def test_run_async_preflight_error_uses_run_id_when_provided(monkeypatch):
    rt = _mk_runtime(monkeypatch, preflight_mode="error")
    monkeypatch.setattr(
        rt,
        "preflight",
        lambda: [FrameworkIssue(code="X", message="m", details={"path": "skills.scan.ttlSecs"})],
    )
    out = await rt.run_async("hi", run_id="RID")
    assert out.node_report.run_id == "RID"
