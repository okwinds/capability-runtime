from __future__ import annotations

from skills_runtime.core.contracts import AgentEvent

from capability_runtime.ui_events.projector import RuntimeUIEventProjector, _AgentCtx
from capability_runtime.ui_events.v1 import StreamLevel


def _ev(t: str, payload: dict) -> AgentEvent:
    return AgentEvent(type=t, timestamp="2026-03-02T00:00:00Z", run_id="r1", turn_id="t1", payload=payload)


def _dump_path(ev) -> list[dict]:
    return [seg.model_dump() for seg in ev.path]


def test_approval_events_without_call_id_still_correlate_to_tool_call_path_via_step_id() -> None:
    """
    Spec（ui-events-hardening D4 / tasks 4.1）：
    当 `approval_requested/approval_decided` payload 缺 `call_id` 但 ctx 提供 `step_id` 时，
    projector 必须 best-effort 把 approvals 事件归属到同一步内的 tool call path（哪来哪去）。

    预期（本用例在当前实现下应为 RED）：
    - approval.*.path 以 tool.requested.path 为前缀，且只多一个 `approval` 段
    - approval.*.data.call_id 被 best-effort 回填为该 step 内的 call_id
    """

    pj = RuntimeUIEventProjector(run_id="r1", level=StreamLevel.UI)
    ctx = _AgentCtx(run_id="r1", capability_id="agent.x", workflow_id="wf", step_id="S1")

    out_tool = pj.on_agent_event(
        _ev("tool_call_requested", payload={"call_id": "c1", "name": "apply_patch", "arguments": {"k": "v"}}),
        ctx=ctx,
    )
    tool_ev = next(e for e in out_tool if e.type == "tool.requested")

    out_req = pj.on_agent_event(
        _ev("approval_requested", payload={"tool": "apply_patch", "approval_key": "ap-1"}),
        ctx=ctx,
    )
    approval_req_ev = next(e for e in out_req if e.type == "approval.requested")

    out_dec = pj.on_agent_event(
        _ev("approval_decided", payload={"tool": "apply_patch", "approval_key": "ap-1", "decision": "approved"}),
        ctx=ctx,
    )
    approval_dec_ev = next(e for e in out_dec if e.type == "approval.decided")

    tool_path = _dump_path(tool_ev)
    approval_req_path = _dump_path(approval_req_ev)
    approval_dec_path = _dump_path(approval_dec_ev)

    assert approval_req_path[: len(tool_path)] == tool_path
    assert len(approval_req_path) == len(tool_path) + 1
    assert approval_req_ev.path[-1].kind == "approval"
    assert approval_req_ev.data.get("call_id") == "c1"
    assert approval_req_ev.evidence is not None
    assert approval_req_ev.evidence.call_id == "c1"

    assert approval_dec_path[: len(tool_path)] == tool_path
    assert len(approval_dec_path) == len(tool_path) + 1
    assert approval_dec_ev.path[-1].kind == "approval"
    assert approval_dec_ev.data.get("call_id") == "c1"
    assert approval_dec_ev.evidence is not None
    assert approval_dec_ev.evidence.call_id == "c1"


def test_approval_events_without_call_id_and_without_step_mapping_emit_diagnostic_signal() -> None:
    """
    Spec（runtime-ui-events-v1 approvals 归属健壮性）：
    approvals 缺 call_id 且无法通过 step_id 恢复归属时，projector 必须输出可诊断信号（不得静默错挂）。
    """

    pj = RuntimeUIEventProjector(run_id="r1", level=StreamLevel.UI)
    ctx = _AgentCtx(run_id="r1", capability_id="agent.x", workflow_id="wf", step_id="S-miss")

    out_req = pj.on_agent_event(
        _ev("approval_requested", payload={"tool": "apply_patch", "approval_key": "ap-miss"}),
        ctx=ctx,
    )
    approval_req_ev = next(e for e in out_req if e.type == "approval.requested")

    assert approval_req_ev.data.get("correlation") == "missing_call_id"
    assert approval_req_ev.data.get("correlation_error", {}).get("kind") == "missing_call_id"
