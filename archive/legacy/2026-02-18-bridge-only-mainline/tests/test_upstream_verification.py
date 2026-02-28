from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from agent_sdk.core.contracts import AgentEvent
from agent_sdk.core.errors import FrameworkError, FrameworkIssue

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


class _FakeAgent:
    def __init__(self, events: List[AgentEvent]):
        self._events = events

    async def run_stream_async(self, task: str, run_id: str | None = None, initial_history=None):
        for ev in self._events:
            yield ev


def _patch_requester_factory(monkeypatch):
    import capability_runtime.runtime as runtime_mod

    def _fake_factory(*, agently_agent):
        return lambda: _FakeRequester()

    monkeypatch.setattr(runtime_mod, "build_openai_compatible_requester_factory", _fake_factory)


def _mk_runtime(monkeypatch, *, cfg: RuntimeConfig) -> Runtime:
    _patch_requester_factory(monkeypatch)
    return Runtime(agently_agent=object(), config=cfg)


def test_runtime_config_has_upstream_verification_defaults():
    cfg = RuntimeConfig(workspace_root=Path("."), config_paths=[])
    assert cfg.upstream_verification_mode == "warn"
    assert cfg.agently_fork_root is None
    assert cfg.skills_runtime_sdk_fork_root is None


def test_verify_upstreams_off_returns_empty(monkeypatch, tmp_path):
    cfg = RuntimeConfig(
        workspace_root=tmp_path,
        config_paths=[],
        upstream_verification_mode="off",
        agently_fork_root=tmp_path / "agently-fork",
        skills_runtime_sdk_fork_root=tmp_path / "sdk-fork",
    )
    rt = _mk_runtime(monkeypatch, cfg=cfg)
    assert rt.verify_upstreams() == []


def test_verify_upstreams_strict_reports_missing_roots(monkeypatch, tmp_path):
    cfg = RuntimeConfig(
        workspace_root=tmp_path,
        config_paths=[],
        upstream_verification_mode="strict",
    )
    rt = _mk_runtime(monkeypatch, cfg=cfg)
    issues = rt.verify_upstreams()
    assert len(issues) == 2
    assert {i.code for i in issues} == {"UPSTREAM_FORK_ROOT_MISSING"}


def test_verify_upstreams_warn_with_matching_roots_has_no_issues(monkeypatch, tmp_path):
    import capability_runtime.runtime as runtime_mod

    agently_root = (tmp_path / "agently").resolve()
    sdk_root = (tmp_path / "skills-runtime-sdk").resolve()

    def _fake_import(name: str):
        if name == "agently":
            return SimpleNamespace(__file__=str(agently_root / "agently" / "__init__.py"))
        if name == "agent_sdk":
            return SimpleNamespace(__file__=str(sdk_root / "packages" / "skills-runtime-sdk-python" / "src" / "agent_sdk" / "__init__.py"))
        raise ImportError(name)

    monkeypatch.setattr(runtime_mod.importlib, "import_module", _fake_import)

    cfg = RuntimeConfig(
        workspace_root=tmp_path,
        config_paths=[],
        upstream_verification_mode="warn",
        agently_fork_root=agently_root,
        skills_runtime_sdk_fork_root=sdk_root,
    )
    rt = _mk_runtime(monkeypatch, cfg=cfg)
    assert rt.verify_upstreams() == []


def test_verify_upstreams_warn_reports_mismatch(monkeypatch, tmp_path):
    import capability_runtime.runtime as runtime_mod

    def _fake_import(name: str):
        if name == "agently":
            return SimpleNamespace(__file__="/opt/other/agently/__init__.py")
        if name == "agent_sdk":
            return SimpleNamespace(__file__="/opt/other/agent_sdk/__init__.py")
        raise ImportError(name)

    monkeypatch.setattr(runtime_mod.importlib, "import_module", _fake_import)

    cfg = RuntimeConfig(
        workspace_root=tmp_path,
        config_paths=[],
        upstream_verification_mode="warn",
        agently_fork_root=tmp_path / "agently-fork",
        skills_runtime_sdk_fork_root=tmp_path / "sdk-fork",
    )
    rt = _mk_runtime(monkeypatch, cfg=cfg)
    issues = rt.verify_upstreams()
    assert len(issues) == 2
    assert {i.code for i in issues} == {"UPSTREAM_NOT_FROM_EXPECTED_FORK"}


def test_verify_upstreams_warn_reports_import_error(monkeypatch, tmp_path):
    import capability_runtime.runtime as runtime_mod

    def _fake_import(name: str):
        raise ImportError(name)

    monkeypatch.setattr(runtime_mod.importlib, "import_module", _fake_import)

    cfg = RuntimeConfig(
        workspace_root=tmp_path,
        config_paths=[],
        upstream_verification_mode="warn",
        agently_fork_root=tmp_path / "agently-fork",
    )
    rt = _mk_runtime(monkeypatch, cfg=cfg)
    issues = rt.verify_upstreams()
    assert len(issues) >= 1
    assert issues[0].code == "UPSTREAM_IMPORT_FAILED"


def test_verify_upstreams_or_raise_raises_framework_error(monkeypatch, tmp_path):
    cfg = RuntimeConfig(
        workspace_root=tmp_path,
        config_paths=[],
        upstream_verification_mode="strict",
    )
    rt = _mk_runtime(monkeypatch, cfg=cfg)
    with pytest.raises(FrameworkError) as exc:
        rt.verify_upstreams_or_raise()
    assert exc.value.code == "UPSTREAM_VERIFICATION_FAILED"


@pytest.mark.asyncio
async def test_run_async_strict_upstream_issues_fail_closed(monkeypatch, tmp_path):
    cfg = RuntimeConfig(
        workspace_root=tmp_path,
        config_paths=[],
        preflight_mode="off",
        upstream_verification_mode="strict",
    )
    rt = _mk_runtime(monkeypatch, cfg=cfg)
    monkeypatch.setattr(
        rt,
        "verify_upstreams",
        lambda: [FrameworkIssue(code="UPSTREAM_NOT_FROM_EXPECTED_FORK", message="m", details={"module": "agently"})],
    )

    out = await rt.run_async("hi", run_id="rid-upstream")
    assert out.node_report.status == "failed"
    assert out.node_report.reason == "upstream_dependency_error"
    assert out.node_report.completion_reason == "upstream_verification_failed"


@pytest.mark.asyncio
async def test_run_async_warn_upstream_issues_are_observable(monkeypatch, tmp_path):
    cfg = RuntimeConfig(
        workspace_root=tmp_path,
        config_paths=[],
        preflight_mode="off",
        upstream_verification_mode="warn",
    )
    rt = _mk_runtime(monkeypatch, cfg=cfg)
    monkeypatch.setattr(
        rt,
        "verify_upstreams",
        lambda: [FrameworkIssue(code="UPSTREAM_NOT_FROM_EXPECTED_FORK", message="m", details={"module": "agently"})],
    )

    fake_events = [
        AgentEvent(type="run_started", ts="2026-02-12T00:00:00Z", run_id="r1", payload={}),
        AgentEvent(type="run_completed", ts="2026-02-12T00:00:01Z", run_id="r1", payload={"final_output": "ok", "events_path": "e.jsonl"}),
    ]
    monkeypatch.setattr(rt, "_get_or_create_agent", lambda: _FakeAgent(fake_events))

    out = await rt.run_async("hi")
    assert out.node_report.status == "success"
    assert out.node_report.meta["upstream_verification_mode"] == "warn"
    assert out.node_report.meta["upstream_issues"][0]["code"] == "UPSTREAM_NOT_FROM_EXPECTED_FORK"


@pytest.mark.asyncio
async def test_run_async_no_upstream_issues_does_not_add_meta(monkeypatch, tmp_path):
    cfg = RuntimeConfig(
        workspace_root=tmp_path,
        config_paths=[],
        preflight_mode="off",
        upstream_verification_mode="warn",
    )
    rt = _mk_runtime(monkeypatch, cfg=cfg)
    monkeypatch.setattr(rt, "verify_upstreams", lambda: [])

    fake_events = [
        AgentEvent(type="run_started", ts="2026-02-12T00:00:00Z", run_id="r1", payload={}),
        AgentEvent(type="run_completed", ts="2026-02-12T00:00:01Z", run_id="r1", payload={"final_output": "ok", "events_path": "e.jsonl"}),
    ]
    monkeypatch.setattr(rt, "_get_or_create_agent", lambda: _FakeAgent(fake_events))

    out = await rt.run_async("hi")
    assert "upstream_issues" not in out.node_report.meta
