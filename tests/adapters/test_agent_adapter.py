"""AgentAdapter 单元测试（以统一 Runtime + mock/bridge 语义为真相源）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from capability_runtime.config import RuntimeConfig
from capability_runtime.protocol.agent import AgentIOSchema, AgentSpec
from capability_runtime.protocol.capability import (
    CapabilityKind,
    CapabilityResult,
    CapabilitySpec,
    CapabilityStatus,
)
from capability_runtime.protocol.context import ExecutionContext
from capability_runtime.runtime import Runtime

from capability_runtime.adapters.agent_adapter import AgentAdapter


def _mk_runtime(*, cfg: RuntimeConfig) -> Runtime:
    rt = Runtime(cfg)
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    return rt


@pytest.mark.asyncio
async def test_mock_handler_can_return_capability_result() -> None:
    def handler(_spec: AgentSpec, _input: Dict[str, Any]) -> CapabilityResult:
        return CapabilityResult(status=CapabilityStatus.PENDING, output={"needs": "approval"})

    rt = _mk_runtime(cfg=RuntimeConfig(mode="mock", mock_handler=handler))
    out = await rt.run("A", context=ExecutionContext(run_id="r1"))
    assert out.status == CapabilityStatus.PENDING
    assert out.output == {"needs": "approval"}


@pytest.mark.asyncio
async def test_mock_handler_can_be_async() -> None:
    async def handler(_spec: AgentSpec, input_dict: Dict[str, Any], _ctx: ExecutionContext) -> Dict[str, Any]:
        return {"ok": True, "x": input_dict.get("x")}

    rt = _mk_runtime(cfg=RuntimeConfig(mode="mock", mock_handler=handler))
    out = await rt.run("A", input={"x": 1}, context=ExecutionContext(run_id="r1"))
    assert out.status == CapabilityStatus.SUCCESS
    assert out.output["ok"] is True
    assert out.output["x"] == 1


def test_build_task_includes_output_schema_and_skills_mentions() -> None:
    rt = _mk_runtime(
        cfg=RuntimeConfig(
            mode="sdk_native",
            workspace_root=Path("."),
            preflight_mode="off",
            skills_config={
                "roots": [],
                "mode": "explicit",
                "max_auto": 3,
                "spaces": [
                    {
                        "id": "sp1",
                        "account": "acct",
                        "domain": "dm",
                        "sources": ["mem1"],
                        "enabled": True,
                    }
                ],
                "sources": [
                    {
                        "id": "mem1",
                        "type": "in-memory",
                        "options": {"namespace": "ns"},
                    }
                ],
                "injection": {"max_bytes": None},
            },
        )
    )

    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A", description="做一件事"),
        output_schema=AgentIOSchema(fields={"score": "int"}),
        skills=["topic-scorer"],
    )

    task = rt._agent_adapter._build_task(spec=spec, input={"x": 1})  # type: ignore[attr-defined]
    assert "## 任务" in task
    assert "做一件事" in task
    assert "## 输入" in task
    assert "## 输出要求" in task
    assert "score" in task
    assert "$[acct:dm].topic-scorer" in task


def test_build_task_prefers_skills_mention_map_when_provided() -> None:
    rt = _mk_runtime(cfg=RuntimeConfig(mode="sdk_native", workspace_root=Path("."), preflight_mode="off"))
    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
        skills=["s1"],
        skills_mention_map={"s1": "$[x:y].s1"},
    )
    task = rt._agent_adapter._build_task(spec=spec, input={})  # type: ignore[attr-defined]
    assert "$[x:y].s1" in task


@pytest.mark.asyncio
async def test_agent_adapter_can_run_in_mock_mode_with_fake_runtime_services() -> None:
    """task 6.3：AgentAdapter 可在不构造 Runtime 的情况下单测（mock RuntimeServices）。"""

    spec = AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"))

    def handler(_spec: AgentSpec, input_dict: Dict[str, Any], _ctx: ExecutionContext) -> Dict[str, Any]:
        return {"ok": True, "x": input_dict.get("x")}

    cfg = RuntimeConfig(mode="mock", mock_handler=handler)

    class _FakeServices:
        def __init__(self) -> None:
            self.config = cfg  # Protocol: @property config

    adapter = AgentAdapter(services=_FakeServices())  # type: ignore[arg-type]

    items = []
    async for it in adapter.execute_stream(spec=spec, input={"x": 1}, context=ExecutionContext(run_id="r1")):
        items.append(it)

    assert len(items) == 1
    assert isinstance(items[0], CapabilityResult)
    assert items[0].status == CapabilityStatus.SUCCESS
    assert items[0].output == {"ok": True, "x": 1}


@pytest.mark.asyncio
async def test_agent_adapter_can_run_in_sdk_native_mode_with_fake_runtime_services() -> None:
    """task 6.3：sdk_native 路径下也可用 fake services 驱动事件流与最终 CapabilityResult。"""

    from skills_runtime.core.contracts import AgentEvent

    spec = AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"))
    cfg = RuntimeConfig(mode="sdk_native", preflight_mode="off")

    class _FakeSdkAgent:
        async def run_stream_async(self, task: str, *, run_id: str, initial_history=None):  # type: ignore[no-untyped-def]
            _ = (task, initial_history)
            yield AgentEvent(type="run_started", timestamp="t0", run_id=run_id, payload={})
            yield AgentEvent(type="run_completed", timestamp="t1", run_id=run_id, payload={"final_output": "ok"})

    class _FakeServices:
        def __init__(self) -> None:
            self.config = cfg
            self.taps: list[str] = []

        def preflight(self):  # type: ignore[no-untyped-def]
            return []

        def create_sdk_agent(self, *, llm_config=None):  # type: ignore[no-untyped-def]
            _ = llm_config
            return _FakeSdkAgent()

        def get_host_meta(self, *, context: ExecutionContext):  # type: ignore[no-untyped-def]
            _ = context
            return {}

        def emit_agent_event_taps(self, *, ev, context: ExecutionContext, capability_id: str) -> None:  # type: ignore[no-untyped-def]
            _ = (context, capability_id)
            self.taps.append(ev.type)

        def call_callback(self, cb, *args) -> None:  # type: ignore[no-untyped-def]
            _ = (cb, args)

        def apply_output_validation(self, *, final_output: str, report, context: Dict[str, Any]) -> None:  # type: ignore[no-untyped-def]
            _ = (final_output, report, context)

        def build_fail_closed_report(self, *, run_id: str, status: str, reason, completion_reason: str, meta: Dict[str, Any]):  # type: ignore[no-untyped-def]
            raise AssertionError("not expected in preflight_mode=off path")

        def redact_issue(self, issue):  # type: ignore[no-untyped-def]
            return {"issue": str(issue)}

    adapter = AgentAdapter(services=_FakeServices())  # type: ignore[arg-type]

    seen = []
    terminal: CapabilityResult | None = None
    async for it in adapter.execute_stream(spec=spec, input={}, context=ExecutionContext(run_id="r1")):
        seen.append(it)
        if isinstance(it, CapabilityResult):
            terminal = it

    assert terminal is not None
    assert terminal.status == CapabilityStatus.SUCCESS
    assert terminal.output == "ok"
