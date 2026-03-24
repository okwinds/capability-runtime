from __future__ import annotations

from typing import Any

import pytest

from capability_runtime import (
    AgentSpec,
    CapabilityKind,
    CapabilitySpec,
    Runtime,
    RuntimeConfig,
    RuntimeServiceFacade,
    RuntimeServiceHandle,
    RuntimeServiceRequest,
    RuntimeSession,
)
from capability_runtime.host_toolkit.turn_delta import TurnDelta
from capability_runtime.service_facade import build_session_context
from capability_runtime.types import NodeReport


def _build_runtime(*, mock_handler) -> Runtime:
    """构造用于 service/session bridge 回归的离线 Runtime。"""

    return Runtime(
        RuntimeConfig(
            mode="mock",
            mock_handler=mock_handler,
        )
    )


def _report(run_id: str) -> NodeReport:
    """构造最小 NodeReport。"""

    return NodeReport(
        status="success",
        reason=None,
        completion_reason="run_completed",
        engine={"name": "skills-runtime-sdk-python", "module": "skills_runtime", "version": "0"},
        bridge={"name": "capability-runtime", "version": "0"},
        run_id=run_id,
        turn_id="t1",
        events_path=f"/tmp/{run_id}.jsonl",
        activated_skills=[],
        tool_calls=[],
        artifacts=[],
        meta={},
    )


def test_build_session_context_prefers_turn_deltas_and_injects_host_meta() -> None:
    """回归：continuity helper 需要经 `__host_meta__` 注入，且 turn_deltas 优先于显式 history。"""

    deltas = [
        TurnDelta(
            session_id="session-1",
            host_turn_id="turn-1",
            run_id="run-1",
            user_input="u1",
            final_output="a1",
            node_report=_report("run-1"),
            events_path="/tmp/run-1.jsonl",
        )
    ]
    session = RuntimeSession(
        session_id="session-1",
        host_turn_id="turn-2",
        history=[{"role": "user", "content": "should-not-win"}],
        metadata={"tenant": "demo"},
    )

    overlay = build_session_context(session=session, turn_deltas=deltas)

    assert overlay["__host_meta__"]["session_id"] == "session-1"
    assert overlay["__host_meta__"]["host_turn_id"] == "turn-2"
    assert overlay["__host_meta__"]["metadata"] == {"tenant": "demo"}
    assert overlay["__host_meta__"]["initial_history"] == [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
    ]


@pytest.mark.asyncio
async def test_runtime_service_facade_start_run_and_stream_reuse_runtime_ui_surface() -> None:
    """回归：service facade 应复用 runtime UI surface，并保持稳定 run_id/session_id。"""

    def mock_handler(spec, input, context=None) -> Any:
        host_meta = dict(getattr(context, "bag", {}) or {}).get("__host_meta__", {})
        return {
            "handled_by": spec.base.id,
            "session_id": host_meta.get("session_id"),
            "initial_history": host_meta.get("initial_history"),
        }

    rt = _build_runtime(mock_handler=mock_handler)
    rt.register(AgentSpec(base=CapabilitySpec(id="agent.service", kind=CapabilityKind.AGENT, name="Service Agent")))

    facade = RuntimeServiceFacade(rt)
    request = RuntimeServiceRequest(
        capability_id="agent.service",
        input={"topic": "demo"},
        session=RuntimeSession(
            session_id="session-1",
            host_turn_id="turn-1",
            history=[{"role": "user", "content": "hi"}],
        ),
        transport="jsonl",
    )

    handle = await facade.start(request)
    assert isinstance(handle, RuntimeServiceHandle)
    assert handle.capability_id == "agent.service"
    assert handle.run_id
    assert handle.session_id == "session-1"

    result = await facade.run(request)
    assert result.output == {
        "handled_by": "agent.service",
        "session_id": "session-1",
        "initial_history": [{"role": "user", "content": "hi"}],
    }

    chunks = []
    async for chunk in facade.stream(handle):
        chunks.append(chunk)
        if '"status":"completed"' in chunk:
            break

    assert chunks, "expected JSONL stream output"
    assert chunks[0].startswith("{")
    assert '"type":"run.status"' in chunks[0]


@pytest.mark.asyncio
async def test_runtime_service_facade_supports_sse_transport() -> None:
    """回归：同一 façade 需要支持 SSE 子集 framing。"""

    rt = _build_runtime(mock_handler=lambda spec, input, context=None: {"ok": True})
    rt.register(AgentSpec(base=CapabilitySpec(id="agent.sse", kind=CapabilityKind.AGENT, name="SSE Agent")))
    facade = RuntimeServiceFacade(rt)

    handle = await facade.start(
        RuntimeServiceRequest(
            capability_id="agent.sse",
            input={},
            session=RuntimeSession(session_id="session-sse"),
            transport="sse",
        )
    )

    chunks = []
    async for chunk in facade.stream(handle):
        chunks.append(chunk)
        if 'status":"completed"' in chunk:
            break

    assert chunks, "expected SSE stream output"
    assert chunks[0].startswith("data: ")


@pytest.mark.asyncio
async def test_runtime_service_facade_reuses_single_run_per_handle_and_releases_completed_handle() -> None:
    """同一 handle 不得重复执行；完成后 handle 应回收。"""

    calls = {"count": 0}

    def mock_handler(spec, input, context=None) -> Any:
        _ = (spec, input, context)
        calls["count"] += 1
        return {"ok": True, "call_index": calls["count"]}

    rt = _build_runtime(mock_handler=mock_handler)
    rt.register(AgentSpec(base=CapabilitySpec(id="agent.once", kind=CapabilityKind.AGENT, name="Once Agent")))
    facade = RuntimeServiceFacade(rt)

    handle = await facade.start(
        RuntimeServiceRequest(
            capability_id="agent.once",
            input={},
            session=RuntimeSession(session_id="session-once"),
        )
    )

    assert calls["count"] == 0

    chunks = [chunk async for chunk in facade.stream(handle)]
    assert chunks
    assert calls["count"] == 1
    assert handle.run_id not in facade._handles

    with pytest.raises(KeyError):
        _ = [chunk async for chunk in facade.stream(handle)]

    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_runtime_service_facade_run_prefers_session_turn_deltas_for_continuity() -> None:
    """façade 层必须真正把 session.turn_deltas 接到 initial_history。"""

    def mock_handler(spec, input, context=None) -> Any:
        _ = (spec, input)
        host_meta = dict(getattr(context, "bag", {}) or {}).get("__host_meta__", {})
        return {
            "session_id": host_meta.get("session_id"),
            "host_turn_id": host_meta.get("host_turn_id"),
            "initial_history": host_meta.get("initial_history"),
        }

    rt = _build_runtime(mock_handler=mock_handler)
    rt.register(AgentSpec(base=CapabilitySpec(id="agent.delta", kind=CapabilityKind.AGENT, name="Delta Agent")))
    facade = RuntimeServiceFacade(rt)

    turn_deltas = [
        TurnDelta(
            session_id="session-delta",
            host_turn_id="turn-prev",
            run_id="run-prev",
            user_input="delta-user",
            final_output="delta-assistant",
            node_report=_report("run-prev"),
            events_path="/tmp/run-prev.jsonl",
        )
    ]
    request = RuntimeServiceRequest(
        capability_id="agent.delta",
        input={},
        session=RuntimeSession(
            session_id="session-delta",
            host_turn_id="turn-now",
            history=[{"role": "user", "content": "history should lose"}],
            turn_deltas=turn_deltas,
        ),
    )

    result = await facade.run(request)
    assert result.output == {
        "session_id": "session-delta",
        "host_turn_id": "turn-now",
        "initial_history": [
            {"role": "user", "content": "delta-user"},
            {"role": "assistant", "content": "delta-assistant"},
        ],
    }
