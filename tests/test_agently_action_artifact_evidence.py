from __future__ import annotations

from skills_runtime.core.contracts import AgentEvent

from capability_runtime import CapabilityResult, CapabilityStatus
from capability_runtime.reporting.node_report import NodeReportBuilder
from capability_runtime.types import NodeReport
from capability_runtime.ui_events.projector import RuntimeUIEventProjector
from capability_runtime.ui_events.v1 import StreamLevel


def _ev(t: str, *, payload=None) -> AgentEvent:
    """构造最小 AgentEvent。"""

    return AgentEvent(type=t, timestamp="2026-05-31T00:00:00Z", run_id="run-action", turn_id="turn-1", payload=payload or {})


def test_action_artifact_reference_summary_enters_node_report_without_raw_content() -> None:
    """Slice G happy/error：Action artifact 只以 reference 摘要进入 NodeReport。"""

    events = [
        _ev("run_started"),
        _ev("tool_call_requested", payload={"call_id": "call-1", "name": "runtime_action", "arguments": {}}),
        _ev(
            "tool_call_finished",
            payload={
                "call_id": "call-1",
                "tool": "runtime_action",
                "result": {
                    "ok": True,
                    "data": {
                        "raw_text": "RAW_ACTION_BODY_SHOULD_NOT_LEAK",
                        "artifact_refs": [
                            {
                                "artifact_id": "art-1",
                                "action_call_id": "action-call-1",
                                "artifact_type": "file",
                                "label": "stdout",
                                "media_type": "text/plain",
                                "source": "runtime_action",
                                "preview": "RAW_PREVIEW_SHOULD_NOT_LEAK",
                                "value": "RAW_VALUE_SHOULD_NOT_LEAK",
                            },
                            {
                                "artifact_id": "art-1",
                                "action_call_id": "action-call-1",
                                "artifact_type": "file",
                                "label": "stdout duplicate",
                                "media_type": "text/plain",
                            },
                            {
                                "artifact_id": "",
                                "preview": "MALFORMED_RAW_SHOULD_NOT_LEAK",
                            },
                        ],
                    },
                },
            },
        ),
        _ev("run_completed", payload={"wal_locator": "wal://run-action"}),
    ]

    report = NodeReportBuilder().build(events=events)

    assert report.artifacts == ["agently-action://art-1"]
    assert report.meta["action_artifacts"] == [
        {
            "artifact_id": "art-1",
            "action_call_id": "action-call-1",
            "artifact_type": "file",
            "label": "stdout",
            "media_type": "text/plain",
            "source": "runtime_action",
        }
    ]
    assert report.meta["runtime_action_artifact_refs"] == ["runtime-action://art-1"]
    assert report.meta["agently_action_artifacts"] == report.meta["action_artifacts"]
    assert report.meta["action_artifact_diagnostics"] == [
        {"code": "ACTION_ARTIFACT_INVALID", "index": 2, "source": "tool_call_finished"}
    ]
    assert report.meta["agently_action_artifact_diagnostics"] == report.meta["action_artifact_diagnostics"]
    assert report.tool_calls[0].data == {
        "artifact_refs": [
            {
                "artifact_id": "art-1",
                "action_call_id": "action-call-1",
                "artifact_type": "file",
                "label": "stdout",
                "media_type": "text/plain",
                "source": "runtime_action",
            }
        ]
    }
    dumped = report.model_dump_json()
    assert "RAW_ACTION_BODY_SHOULD_NOT_LEAK" not in dumped
    assert "RAW_PREVIEW_SHOULD_NOT_LEAK" not in dumped
    assert "RAW_VALUE_SHOULD_NOT_LEAK" not in dumped
    assert "MALFORMED_RAW_SHOULD_NOT_LEAK" not in dumped


def test_invalid_only_action_artifact_payload_never_falls_back_to_raw_data() -> None:
    """Slice G regression：只有非法 artifact 容器时也不能回退泄露原始 data。"""

    events = [
        _ev("run_started"),
        _ev("tool_call_requested", payload={"call_id": "call-invalid", "name": "runtime_action", "arguments": {}}),
        _ev(
            "tool_call_finished",
            payload={
                "call_id": "call-invalid",
                "tool": "runtime_action",
                "result": {
                    "ok": True,
                    "data": {
                        "raw_text": "INVALID_ONLY_RAW_BODY_SHOULD_NOT_LEAK",
                        "artifact_refs": [
                            {
                                "artifact_id": "",
                                "preview": "INVALID_ONLY_PREVIEW_SHOULD_NOT_LEAK",
                                "value": "INVALID_ONLY_VALUE_SHOULD_NOT_LEAK",
                            }
                        ],
                    },
                },
            },
        ),
        _ev("run_completed", payload={"wal_locator": "wal://run-action"}),
    ]

    report = NodeReportBuilder().build(events=events)

    assert report.artifacts == []
    assert report.tool_calls[0].data == {"artifact_refs": []}
    assert report.meta["action_artifact_diagnostics"] == [
        {"code": "ACTION_ARTIFACT_INVALID", "index": 0, "source": "tool_call_finished"}
    ]
    dumped = report.model_dump_json()
    assert "INVALID_ONLY_RAW_BODY_SHOULD_NOT_LEAK" not in dumped
    assert "INVALID_ONLY_PREVIEW_SHOULD_NOT_LEAK" not in dumped
    assert "INVALID_ONLY_VALUE_SHOULD_NOT_LEAK" not in dumped


def test_ui_evidence_projects_action_artifact_reference_without_body() -> None:
    """Slice G UI：UI evidence 只暴露 artifact ref，不读取 artifact 原文。"""

    projector = RuntimeUIEventProjector(run_id="run-action", level=StreamLevel.UI)
    terminal = projector.on_terminal(
        result=CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            node_report=NodeReport(
                status="success",
                completion_reason="run_completed",
                run_id="run-action",
                events_path="wal://run-action",
                artifacts=["agently-action://art-1"],
                meta={
                    "runtime_action_artifact_refs": ["runtime-action://art-1"],
                    "action_artifacts": [
                        {
                            "artifact_id": "art-1",
                            "action_call_id": "action-call-1",
                            "artifact_type": "file",
                            "label": "stdout",
                            "media_type": "text/plain",
                            "source": "runtime_action",
                            "preview": "RAW_UI_PREVIEW_SHOULD_NOT_LEAK",
                        }
                    ]
                },
            ),
        )
    )[0]

    assert terminal.evidence is not None
    assert terminal.evidence.artifact_ref == "runtime-action://art-1"
    dumped = terminal.model_dump_json(by_alias=True)
    assert "RAW_UI_PREVIEW_SHOULD_NOT_LEAK" not in dumped
    assert "preview" not in dumped


def test_ui_evidence_accepts_legacy_action_artifact_reference() -> None:
    """兼容旧 evidence locator，但新写入不再使用上游品牌 scheme。"""

    projector = RuntimeUIEventProjector(run_id="run-action", level=StreamLevel.UI)
    terminal = projector.on_terminal(
        result=CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            node_report=NodeReport(
                status="success",
                completion_reason="run_completed",
                run_id="run-action",
                events_path="wal://run-action",
                artifacts=["agently-action://legacy-art"],
                meta={},
            ),
        )
    )[0]

    assert terminal.evidence is not None
    assert terminal.evidence.artifact_ref == "agently-action://legacy-art"
