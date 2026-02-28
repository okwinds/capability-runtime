from __future__ import annotations

from skills_runtime.core.contracts import AgentEvent

from capability_runtime.ui_events.projector import RuntimeUIEventProjector, _AgentCtx
from capability_runtime.ui_events.v1 import StreamLevel


def _ev(t: str, payload: dict) -> AgentEvent:
    return AgentEvent(type=t, timestamp="2026-02-10T00:00:00Z", run_id="r1", turn_id="t1", payload=payload)


def test_skill_injected_maps_skill_exec_path_to_skill_locator_best_effort() -> None:
    pj = RuntimeUIEventProjector(run_id="r1", level=StreamLevel.UI)
    ctx = _AgentCtx(run_id="r1", capability_id="agent.x")

    injected = _ev(
        "skill_injected",
        payload={
            "namespace": "acme:platform",
            "skill_locator": "loc-123",
            "skill_name": "demo-skill",
            "skill_path": "/skills/demo-skill/SKILL.md",
            "mention_text": "$[acme:platform].demo-skill",
        },
    )
    pj.on_agent_event(injected, ctx=ctx)

    tool_req = _ev(
        "tool_call_requested",
        payload={
            "call_id": "c1",
            "name": "skill_exec",
            "arguments": {"mention_text": "$[acme:platform].demo-skill"},
        },
    )
    out = pj.on_agent_event(tool_req, ctx=ctx)
    tool_ev = next(e for e in out if e.type == "tool.requested")
    kinds = [seg.kind for seg in tool_ev.path]
    assert "skill" in kinds
    assert any(seg.kind == "skill" and seg.id == "loc-123" for seg in tool_ev.path)


def test_non_skill_tools_do_not_force_skill_attribution() -> None:
    pj = RuntimeUIEventProjector(run_id="r1", level=StreamLevel.UI)
    ctx = _AgentCtx(run_id="r1", capability_id="agent.x")

    tool_req = _ev(
        "tool_call_requested",
        payload={"call_id": "c1", "name": "shell_exec", "arguments": {"argv": ["echo", "hi"]}},
    )
    out = pj.on_agent_event(tool_req, ctx=ctx)
    tool_ev = next(e for e in out if e.type == "tool.requested")
    assert all(seg.kind != "skill" for seg in tool_ev.path)

