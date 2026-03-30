from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from skills_runtime.core.contracts import AgentEvent
from skills_runtime.core.errors import FrameworkError, FrameworkIssue

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
    """离线 fake SDK Agent：回放固定事件，并记录 run_id/initial_history。"""

    last_instance = None

    def __init__(self, **kwargs: Any) -> None:
        _FakeAgent.last_instance = self
        self.kwargs = kwargs
        self.last_run_id: Optional[str] = None
        self.last_initial_history: Optional[List[Dict[str, Any]]] = None

    async def run_stream_async(
        self,
        task: str,
        *,
        run_id: Optional[str] = None,
        initial_history: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[AgentEvent]:
        _ = task
        self.last_run_id = run_id
        self.last_initial_history = initial_history

        yield AgentEvent(type="run_started", timestamp="2026-02-10T00:00:00Z", run_id=run_id or "r1", payload={})
        yield AgentEvent(
            type="run_completed",
            timestamp="2026-02-10T00:00:01Z",
            run_id=run_id or "r1",
            payload={"final_output": "ok", "wal_locator": "wal.jsonl"},
        )


def _mk_runtime(monkeypatch: pytest.MonkeyPatch, *, preflight_mode: str, config_paths: Optional[List[Path]] = None) -> Runtime:
    monkeypatch.setattr("skills_runtime.core.agent.Agent", _FakeAgent)
    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=Path("."),
            sdk_config_paths=list(config_paths or []),
            preflight_mode=preflight_mode,  # type: ignore[arg-type]
        )
    )
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    return rt


@pytest.mark.asyncio
async def test_run_preflight_error_returns_failed_node_report(monkeypatch):
    rt = _mk_runtime(monkeypatch, preflight_mode="error")
    monkeypatch.setattr(
        rt,
        "preflight",
        lambda: [FrameworkIssue(code="X", message="m", details={"path": "skills.scan.ttlSecs"})],
    )

    ctx = ExecutionContext(run_id="r-preflight-error")
    out = await rt.run("A", context=ctx)
    assert out.status == CapabilityStatus.FAILED
    assert out.node_report is not None
    assert out.node_report.status == "failed"
    assert out.node_report.reason == "skill_config_error"
    assert out.node_report.completion_reason == "preflight_failed"
    assert out.node_report.meta["skill_issue"]["code"] == "SKILL_PREFLIGHT_FAILED"
    assert out.node_report.meta["skill_issue"]["details"]["issues"][0]["code"] == "X"


@pytest.mark.asyncio
async def test_run_preflight_warn_injects_meta(monkeypatch):
    rt = _mk_runtime(monkeypatch, preflight_mode="warn")
    monkeypatch.setattr(
        rt,
        "preflight",
        lambda: [FrameworkIssue(code="X", message="m", details={"path": "skills.scan.ttlSecs"})],
    )
    ctx = ExecutionContext(run_id="r-preflight-warn")
    out = await rt.run("A", context=ctx)
    assert out.node_report is not None
    assert out.node_report.status == "success"
    assert out.node_report.meta["preflight_mode"] == "warn"
    assert out.node_report.meta["preflight_issues"][0]["code"] == "X"


@pytest.mark.asyncio
async def test_run_preflight_off_does_not_call_preflight(monkeypatch):
    rt = _mk_runtime(monkeypatch, preflight_mode="off")
    monkeypatch.setattr(rt, "preflight", lambda: (_ for _ in ()).throw(RuntimeError("should not call")))

    out = await rt.run("A", context=ExecutionContext(run_id="r-preflight-off"))
    assert out.status == CapabilityStatus.SUCCESS
    assert out.node_report is not None
    assert out.node_report.status == "success"


@pytest.mark.asyncio
async def test_run_preflight_error_does_not_fail_open_when_preflight_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    回归护栏：SkillsManager.preflight 抛异常时不得 fail-open。

    期望：
    - preflight_mode="error" 时仍应 fail-closed；
    - NodeReport.meta 中包含最小披露的 preflight 异常摘要/issue。
    """

    rt = _mk_runtime(monkeypatch, preflight_mode="error")

    import skills_runtime.skills.manager as skills_manager_mod

    def boom(_self) -> list[FrameworkIssue]:
        raise RuntimeError("preflight boom")

    monkeypatch.setattr(skills_manager_mod.SkillsManager, "preflight", boom, raising=True)

    out = await rt.run("A", context=ExecutionContext(run_id="r-preflight-raise"))
    assert out.status == CapabilityStatus.FAILED
    assert out.node_report is not None
    assert out.node_report.reason == "skill_config_error"

    issue_details = out.node_report.meta.get("skill_issue", {}).get("details", {})
    issues = issue_details.get("issues") or []
    assert any(i.get("code") == "SKILL_PREFLIGHT_EXCEPTION" for i in issues)


@pytest.mark.asyncio
async def test_preflight_detects_legacy_roots_overlay(tmp_path, monkeypatch):
    overlay = tmp_path / "bad.yaml"
    overlay.write_text("skills:\n  roots:\n    - /tmp\n", encoding="utf-8")
    rt = _mk_runtime(monkeypatch, preflight_mode="warn", config_paths=[overlay])
    out = await rt.run("A", context=ExecutionContext(run_id="r-preflight-roots"))
    assert out.node_report is not None
    issues = out.node_report.meta.get("preflight_issues") or []
    assert any(i.get("code") == "SKILL_CONFIG_LEGACY_ROOTS_UNSUPPORTED" for i in issues)


@pytest.mark.asyncio
async def test_preflight_warn_mode_does_not_block_on_unknown_scan_option(tmp_path, monkeypatch):
    overlay = tmp_path / "warn.yaml"
    overlay.write_text("skills:\n  scan:\n    ttlSecs: 10\n", encoding="utf-8")
    rt = _mk_runtime(monkeypatch, preflight_mode="warn", config_paths=[overlay])
    out = await rt.run("A", context=ExecutionContext(run_id="r-preflight-unknown-scan"))
    assert out.node_report is not None
    issues = out.node_report.meta.get("preflight_issues") or []
    assert any(i.get("code") == "SKILL_CONFIG_UNKNOWN_SCAN_OPTION" for i in issues)


def test_preflight_broken_overlay_yaml_surfaces_issue(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    回归护栏：损坏的 overlay 不能被静默吞掉为“无 issue”。

    期望：
    - Runtime 仍可在 warn 模式构造（保持最小侵入）；
    - preflight() 至少返回一个与 overlay 加载失败相关的 issue。
    """

    overlay = tmp_path / "broken.yaml"
    overlay.write_text("skills:\n  roots: [\n", encoding="utf-8")

    rt = _mk_runtime(monkeypatch, preflight_mode="warn", config_paths=[overlay])
    issues = rt.preflight()

    assert issues
    assert any(
        str(getattr(issue, "code", "") or "") == "SKILL_CONFIG_OVERLAY_LOAD_FAILED"
        and str(((getattr(issue, "details", None) or {}).get("path", ""))) == str(overlay)
        for issue in issues
    )


def test_preflight_skills_config_unknown_option_surfaces_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("skills_runtime.core.agent.Agent", _FakeAgent)

    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=Path("."),
            preflight_mode="warn",
            skills_config={"unknown_top_level_key": 1, "roots": ["/tmp"]},
        )
    )
    issues = rt.preflight()

    assert any(str(getattr(issue, "code", "") or "") == "SKILL_CONFIG_UNKNOWN_OPTION" for issue in issues)
    assert any(str(getattr(issue, "code", "") or "") == "SKILL_CONFIG_LEGACY_ROOTS_UNSUPPORTED" for issue in issues)


@pytest.mark.asyncio
async def test_run_preflight_warn_surfaces_versioning_strategy_drift_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("skills_runtime.core.agent.Agent", _FakeAgent)

    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=Path("."),
            preflight_mode="warn",
            skills_config={"versioning": {"strategy": "TODO"}},
        )
    )
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))

    out = await rt.run("A", context=ExecutionContext(run_id="r-preflight-versioning-warn"))

    assert out.status == CapabilityStatus.SUCCESS
    assert out.node_report is not None
    issues = out.node_report.meta.get("preflight_issues") or []
    assert any(
        i.get("code") == "SKILL_CONFIG_VERSIONING_STRATEGY_DRIFT"
        and ((i.get("details") or {}).get("path")) == "versioning.strategy"
        for i in issues
    )


@pytest.mark.asyncio
async def test_run_preflight_error_fails_closed_on_runtimeconfig_skills_config_issues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("skills_runtime.core.agent.Agent", _FakeAgent)

    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=Path("."),
            preflight_mode="error",
            skills_config={"unknown_top_level_key": 1},
        )
    )
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))

    out = await rt.run("A", context=ExecutionContext(run_id="r-preflight-skills-config"))

    assert out.status == CapabilityStatus.FAILED
    assert out.error_code == "PREFLIGHT_FAILED"
    assert out.node_report is not None
    issues = (((out.node_report.meta.get("skill_issue") or {}).get("details") or {}).get("issues") or [])
    assert any(i.get("code") == "SKILL_CONFIG_UNKNOWN_OPTION" for i in issues)


@pytest.mark.asyncio
async def test_run_preflight_error_fails_closed_on_versioning_strategy_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("skills_runtime.core.agent.Agent", _FakeAgent)

    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=Path("."),
            preflight_mode="error",
            skills_config={"skills": {"versioning": {"strategy": "TODO"}}},
        )
    )
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))

    out = await rt.run("A", context=ExecutionContext(run_id="r-preflight-versioning-error"))

    assert out.status == CapabilityStatus.FAILED
    assert out.error_code == "PREFLIGHT_FAILED"
    assert out.node_report is not None
    issues = (((out.node_report.meta.get("skill_issue") or {}).get("details") or {}).get("issues") or [])
    assert any(
        i.get("code") == "SKILL_CONFIG_VERSIONING_STRATEGY_DRIFT"
        and ((i.get("details") or {}).get("path")) == "skills.versioning.strategy"
        for i in issues
    )


def test_runtime_init_fails_closed_when_scan_raises_in_error_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    回归护栏：初始化期 `SkillsManager.scan()` 自身抛异常时，error 模式不得继续启动。
    """

    import skills_runtime.skills.manager as skills_manager_mod

    def boom(_self):
        raise RuntimeError("scan boom")

    monkeypatch.setattr("skills_runtime.core.agent.Agent", _FakeAgent)
    monkeypatch.setattr(skills_manager_mod.SkillsManager, "scan", boom, raising=True)

    with pytest.raises(FrameworkError, match="scan failed|scan boom|Skills scan"):
        Runtime(
            RuntimeConfig(
                mode="sdk_native",
                workspace_root=Path("."),
                preflight_mode="error",
            )
        )


def test_runtime_init_fails_closed_when_broken_overlay_yaml_in_error_mode(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    回归护栏：error 模式下损坏 overlay 必须阻断初始化。
    """

    overlay = tmp_path / "broken-error.yaml"
    overlay.write_text("skills:\n  roots: [\n", encoding="utf-8")

    monkeypatch.setattr("skills_runtime.core.agent.Agent", _FakeAgent)

    with pytest.raises(FrameworkError):
        Runtime(
            RuntimeConfig(
                mode="sdk_native",
                workspace_root=Path("."),
                sdk_config_paths=[overlay],
                preflight_mode="error",
            )
        )
