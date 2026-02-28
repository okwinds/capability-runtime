from __future__ import annotations

from pathlib import Path

import pytest

from agent_sdk.core.contracts import AgentEvent
from agent_sdk.tools.protocol import ToolSpec

import capability_runtime.bridge as bridge_mod
from capability_runtime.bridge import Runtime, RuntimeConfig


class _FakeRequester:
    def generate_request_data(self):
        return type(
            "Req",
            (),
            {
                "data": {"messages": []},
                "request_options": {},
                "stream": True,
                "headers": {},
                "client_options": {},
                "request_url": "x",
            },
        )()

    async def request_model(self, request_data):
        yield ("message", "[DONE]")


def _patch_requester_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_build(*, agently_agent):
        _ = agently_agent
        return lambda: _FakeRequester()

    monkeypatch.setattr(bridge_mod, "build_openai_compatible_requester_factory", fake_build)


class _FakeAgent:
    last_instance = None

    def __init__(
        self,
        *,
        workspace_root,
        config_paths,
        env_vars,
        backend,
        human_io,
        approval_provider,
        cancel_checker,
    ):
        _FakeAgent.last_instance = self
        self.registered: list[tuple[str, bool]] = []

    def register_tool(self, spec, handler, *, override: bool = False) -> None:
        _ = handler
        self.registered.append((str(getattr(spec, "name", "")), bool(override)))

    async def run_stream_async(self, task, *, run_id=None, initial_history=None):
        _ = task
        _ = run_id
        _ = initial_history
        yield AgentEvent(type="run_started", ts="2026-02-10T00:00:00Z", run_id="r1", payload={})
        yield AgentEvent(
            type="run_completed",
            ts="2026-02-10T00:00:01Z",
            run_id="r1",
            payload={"final_output": "ok", "events_path": "wal.jsonl"},
        )


@pytest.mark.asyncio
async def test_register_tool_is_lazy_and_injected_on_first_run(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_requester_factory(monkeypatch)
    monkeypatch.setattr(bridge_mod, "Agent", _FakeAgent)

    cfg = RuntimeConfig(
        workspace_root=Path("."),
        config_paths=[],
        preflight_mode="off",
        upstream_verification_mode="off",
    )
    rt = Runtime(agently_agent=object(), config=cfg)

    assert rt._agent is None

    spec = ToolSpec(
        name="run_workflow",
        description="demo",
        parameters={"type": "object", "properties": {"workflow_id": {"type": "string"}}, "required": ["workflow_id"]},
        requires_approval=True,
    )

    def handler(call, ctx):
        _ = call
        _ = ctx
        raise RuntimeError("should not be executed in this test")

    rt.register_tool(spec=spec, handler=handler, override=False)
    assert rt._agent is None  # 仍应保持懒加载

    out = await rt.run_async("hi")
    assert out.final_output == "ok"

    agent = _FakeAgent.last_instance
    assert agent is not None
    assert ("run_workflow", False) in agent.registered

