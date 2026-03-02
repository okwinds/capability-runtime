from __future__ import annotations

"""
离线单测：NodeReport.status -> CapabilityStatus 映射护栏。

说明：
- 编排分支必须读取 NodeReport.status/reason，而不是解析自由文本 output；
- needs_approval / incomplete 不得被折叠为 failed（避免误判）。
"""

from capability_runtime import CapabilityStatus, NodeReport
from capability_runtime.services import map_node_status


def _report(*, status: str, reason: str | None = None) -> NodeReport:
    return NodeReport(
        status=status,  # type: ignore[arg-type]
        reason=reason,
        completion_reason="",
        engine={"name": "skills-runtime-sdk-python", "module": "skills_runtime"},
        bridge={"name": "capability-runtime"},
        run_id="r1",
        turn_id=None,
        events_path=None,
        activated_skills=[],
        tool_calls=[],
        artifacts=[],
        meta={},
    )


def test_map_node_status_success_and_failed() -> None:
    assert map_node_status(_report(status="success")) == CapabilityStatus.SUCCESS
    assert map_node_status(_report(status="failed")) == CapabilityStatus.FAILED


def test_map_node_status_needs_approval_is_pending() -> None:
    assert map_node_status(_report(status="needs_approval", reason="approval_pending")) == CapabilityStatus.PENDING


def test_map_node_status_incomplete_cancelled_vs_pending() -> None:
    assert map_node_status(_report(status="incomplete", reason="cancelled")) == CapabilityStatus.CANCELLED
    assert map_node_status(_report(status="incomplete", reason="budget_exceeded")) == CapabilityStatus.PENDING
    assert map_node_status(_report(status="incomplete", reason=None)) == CapabilityStatus.PENDING

