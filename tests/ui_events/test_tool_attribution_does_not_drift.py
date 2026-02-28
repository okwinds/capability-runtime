from __future__ import annotations

from skills_runtime.core.contracts import AgentEvent

from agently_skills_runtime.ui_events.projector import RuntimeUIEventProjector, _AgentCtx
from agently_skills_runtime.ui_events.v1 import StreamLevel


def _ev(t: str, payload: dict) -> AgentEvent:
    return AgentEvent(type=t, timestamp="2026-02-10T00:00:00Z", run_id="r1", turn_id="t1", payload=payload)


def test_tool_finished_reuses_requested_origin_path_even_if_ctx_changes() -> None:
    pj = RuntimeUIEventProjector(run_id="r1", level=StreamLevel.UI)

    ctx_a = _AgentCtx(run_id="r1", capability_id="agent.x", workflow_id="wf", step_id="A")
    ctx_b = _AgentCtx(run_id="r1", capability_id="agent.x", workflow_id="wf", step_id="B")

    requested = _ev("tool_call_requested", payload={"call_id": "c1", "name": "apply_patch", "arguments": {"k": "v"}})
    finished = _ev(
        "tool_call_finished",
        payload={"call_id": "c1", "tool": "apply_patch", "result": {"ok": True, "data": {"x": 1}}},
    )

    out_req = pj.on_agent_event(requested, ctx=ctx_a)
    out_fin = pj.on_agent_event(finished, ctx=ctx_b)

    req_ev = next(e for e in out_req if e.type == "tool.requested")
    fin_ev = next(e for e in out_fin if e.type == "tool.finished")

    # “哪来哪去”：finished 的 path 应与 requested 在同一节点实例上归并（不随 ctx 漂移）
    assert [s.model_dump() for s in fin_ev.path] == [s.model_dump() for s in req_ev.path]
