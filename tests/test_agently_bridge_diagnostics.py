from __future__ import annotations

from pathlib import Path

import pytest

from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec, Runtime, RuntimeConfig
from skills_runtime.llm.chat_sse import ChatStreamEvent
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall


def test_agently_bridge_diagnostics_reports_version_source_and_responses_support() -> None:
    """
    diagnostics 必须基于当前安装态 Agently 生成脱敏摘要，用于 NodeReport.bridge["agently"]。
    """

    from capability_runtime.adapters.agently_compat import collect_agently_bridge_diagnostics

    diagnostics = collect_agently_bridge_diagnostics(requester_strategy="responses")

    assert diagnostics.requester_strategy == "responses"
    assert diagnostics.installed_version in (None, "4.1.3.1")
    assert isinstance(diagnostics.supports_openai_responses, bool)
    assert isinstance(diagnostics.metadata_source_consistent, bool)
    if diagnostics.imported_from is not None:
        assert Path(diagnostics.imported_from).name == "__init__.py"


def test_agently_bridge_diagnostics_summary_is_redacted_and_stable() -> None:
    """
    diagnostics 摘要只允许暴露版本、来源和能力布尔值，不能泄露 headers/API key。
    """

    from capability_runtime.adapters.agently_compat import (
        AgentlyBridgeDiagnostics,
        summarize_agently_bridge_diagnostics,
    )

    diagnostics = AgentlyBridgeDiagnostics(
        installed_version="4.1.3.1",
        imported_from="/tmp/site-packages/agently/__init__.py",
        requester_strategy="responses",
        supports_openai_responses=True,
        metadata_source_consistent=True,
    )

    summary = summarize_agently_bridge_diagnostics(diagnostics)

    assert summary == {
        "installed_version": "4.1.3.1",
        "imported_from": "/tmp/site-packages/agently/__init__.py",
        "requester_strategy": "responses",
        "supports_openai_responses": True,
        "metadata_source_consistent": True,
    }
    rendered = repr(summary).lower()
    assert "authorization" not in rendered
    assert "api_key" not in rendered
    assert "bearer" not in rendered


@pytest.mark.asyncio
async def test_bridge_mode_node_report_includes_agently_diagnostics_summary(tmp_path: Path) -> None:
    """
    bridge mode 的正常 NodeReport 必须在 bridge["agently"] 暴露脱敏 diagnostics 摘要。
    """

    backend = FakeChatBackend(calls=[FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="ok"), ChatStreamEvent(type="completed")])])
    rt = Runtime(
        RuntimeConfig(
            mode="bridge",
            workspace_root=tmp_path,
            sdk_backend=backend,
            requester_strategy="responses",
            preflight_mode="off",
        )
    )
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))

    result = await rt.run("A")

    assert result.node_report is not None
    agently_summary = result.node_report.bridge.get("agently")
    assert isinstance(agently_summary, dict)
    assert agently_summary["requester_strategy"] == "responses"
    assert agently_summary["installed_version"] == "4.1.3.1"
    assert agently_summary["supports_openai_responses"] is True
    rendered = repr(agently_summary).lower()
    assert "authorization" not in rendered
    assert "api_key" not in rendered


def test_bridge_mode_fail_closed_report_includes_agently_diagnostics_summary(tmp_path: Path) -> None:
    """
    fail-closed NodeReport 也必须携带同样的 Agently diagnostics 摘要。
    """

    backend = FakeChatBackend(calls=[])
    rt = Runtime(
        RuntimeConfig(
            mode="bridge",
            workspace_root=tmp_path,
            sdk_backend=backend,
            requester_strategy="chat_completions",
            preflight_mode="off",
        )
    )

    report = rt.build_fail_closed_report(
        run_id="run-fail",
        status="failed",
        reason="engine_error",
        completion_reason="forced",
        meta={},
    )

    agently_summary = report.bridge.get("agently")
    assert isinstance(agently_summary, dict)
    assert agently_summary["requester_strategy"] == "chat_completions"
    assert agently_summary["installed_version"] == "4.1.3.1"
