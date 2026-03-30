from __future__ import annotations

from typing import Any, AsyncIterator

import pytest

from capability_runtime import (
    AgentSpec,
    CapabilityKind,
    CapabilitySpec,
    CapabilityStatus,
    Runtime,
    RuntimeConfig,
    RuntimeServiceFacade,
    RuntimeServiceRequest,
    RuntimeSession,
)


def _build_runtime(*, mock_handler, runtime_client=None) -> Runtime:
    runtime = Runtime(RuntimeConfig(mode="mock", mock_handler=mock_handler, runtime_client=runtime_client))
    runtime.register(AgentSpec(base=CapabilitySpec(id="agent.rpc", kind=CapabilityKind.AGENT, name="RPC Agent")))
    return runtime


class _FakeRuntimeClient:
    def __init__(self) -> None:
        self.invoke_requests: list[dict[str, Any]] = []
        self.stream_requests: list[dict[str, Any]] = []
        self.cancel_run_ids: list[str] = []
        self.replay_requests: list[dict[str, Any]] = []

    async def invoke(self, request: dict[str, Any]) -> dict[str, Any]:
        self.invoke_requests.append(request)
        return {
            "status": "success",
            "output": {"mode": "rpc", "run_id": request["run_id"]},
            "metadata": {"source": "fake-rpc"},
        }

    async def stream(self, request: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        self.stream_requests.append(request)
        yield {
            "schema": "capability-runtime.runtime_event.v1",
            "type": "run.status",
            "run_id": request["run_id"],
            "seq": 1,
            "ts_ms": 0,
            "level": request["stream_level"],
            "path": [],
            "data": {"status": "completed"},
            "rid": "1",
        }

    async def cancel(self, *, run_id: str) -> None:
        self.cancel_run_ids.append(run_id)

    async def replay(self, request: dict[str, Any]) -> dict[str, Any]:
        self.replay_requests.append(request)
        return {"ok": True, "run_id": request["run_id"], "workflow_id": request["capability_id"]}


@pytest.mark.asyncio
async def test_runtime_service_facade_defaults_to_local_execution() -> None:
    runtime = _build_runtime(mock_handler=lambda spec, input, context=None: {"mode": "local", "input": input})
    facade = RuntimeServiceFacade(runtime)

    result = await facade.run(RuntimeServiceRequest(capability_id="agent.rpc", input={"topic": "demo"}))

    assert result.status == CapabilityStatus.SUCCESS
    assert result.output == {"mode": "local", "input": {"topic": "demo"}}


@pytest.mark.asyncio
async def test_runtime_service_facade_rpc_requires_runtime_client() -> None:
    runtime = _build_runtime(mock_handler=lambda spec, input, context=None: {"mode": "local"})
    facade = RuntimeServiceFacade(runtime)
    request = RuntimeServiceRequest(capability_id="agent.rpc", input={}, execution_target="rpc")

    with pytest.raises(ValueError, match="runtime_client is required when execution_target='rpc'"):
        await facade.run(request)


@pytest.mark.asyncio
async def test_runtime_service_facade_rpc_run_maps_request_and_result() -> None:
    client = _FakeRuntimeClient()
    runtime = _build_runtime(mock_handler=lambda spec, input, context=None: {"mode": "local"}, runtime_client=client)
    facade = RuntimeServiceFacade(runtime)
    request = RuntimeServiceRequest(
        capability_id="agent.rpc",
        input={"topic": "rpc"},
        session=RuntimeSession(session_id="session-rpc"),
        execution_target="rpc",
        timeout_ms=2500,
        stream_level="lite",
        transport="sse",
    )

    result = await facade.run(request)

    assert result.status == CapabilityStatus.SUCCESS
    assert result.output == {"mode": "rpc", "run_id": client.invoke_requests[0]["run_id"]}
    sent = client.invoke_requests[0]
    assert sent["request_id"]
    assert sent["session_id"] == "session-rpc"
    assert sent["capability_id"] == "agent.rpc"
    assert sent["input"] == {"topic": "rpc"}
    assert sent["timeout_ms"] == 2500
    assert sent["stream_level"] == "lite"
    assert sent["transport"] == "sse"


@pytest.mark.asyncio
async def test_runtime_service_facade_rpc_start_stream_cancel_and_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeRuntimeClient()
    runtime = _build_runtime(mock_handler=lambda spec, input, context=None: {"mode": "local"}, runtime_client=client)
    facade = RuntimeServiceFacade(runtime)

    def _unexpected_start_ui_events_session(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("rpc start must not create local UI session")

    monkeypatch.setattr(runtime, "start_ui_events_session", _unexpected_start_ui_events_session)

    request = RuntimeServiceRequest(
        capability_id="agent.rpc",
        input={"topic": "rpc-stream"},
        session=RuntimeSession(session_id="session-stream"),
        execution_target="rpc",
        transport="jsonl",
    )
    handle = await facade.start(request)

    assert handle.run_id
    assert handle.session_id == "session-stream"
    assert facade._handles[handle.run_id].session is None

    chunks = [chunk async for chunk in facade.stream(handle)]
    assert len(chunks) == 1
    assert chunks[0].startswith("{")
    assert '"run_id":"' + handle.run_id + '"' in chunks[0]
    assert client.stream_requests[0]["run_id"] == handle.run_id
    assert client.stream_requests[0]["transport"] == "jsonl"

    await facade.cancel(handle)
    assert client.cancel_run_ids == [handle.run_id]

    replay = await facade.replay(
        workflow_id="wf.rpc",
        run_id="run-replay",
        current_input={"step": 1},
        execution_target="rpc",
        timeout_ms=1200,
    )
    assert replay == {"ok": True, "run_id": "run-replay", "workflow_id": "wf.rpc"}
    assert client.replay_requests == [
        {
            "request_id": client.replay_requests[0]["request_id"],
            "run_id": "run-replay",
            "session_id": None,
            "capability_id": "wf.rpc",
            "input": {"step": 1},
            "timeout_ms": 1200,
            "stream_level": "ui",
            "transport": "jsonl",
        }
    ]


@pytest.mark.asyncio
async def test_runtime_service_facade_rpc_run_rejects_invalid_client_result() -> None:
    class _InvalidRuntimeClient(_FakeRuntimeClient):
        async def invoke(self, request: dict[str, Any]) -> dict[str, Any]:
            self.invoke_requests.append(request)
            return {"output": {"missing": "status"}}

    client = _InvalidRuntimeClient()
    runtime = _build_runtime(mock_handler=lambda spec, input, context=None: {"mode": "local"}, runtime_client=client)
    facade = RuntimeServiceFacade(runtime)

    with pytest.raises(TypeError):
        await facade.run(RuntimeServiceRequest(capability_id="agent.rpc", input={}, execution_target="rpc"))
