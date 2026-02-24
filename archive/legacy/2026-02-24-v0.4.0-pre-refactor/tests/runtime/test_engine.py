"""CapabilityRuntime (Engine) 单元测试。"""
from __future__ import annotations

import pytest

from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.protocol.capability import (
    CapabilityKind,
    CapabilityRef,
    CapabilityResult,
    CapabilitySpec,
    CapabilityStatus,
)
from agently_skills_runtime.runtime.engine import CapabilityRuntime, RuntimeConfig


class MockAdapter:
    """返回固定结果的 mock adapter。"""

    def __init__(self, output="mock_output"):
        self._output = output
        self.calls = []

    async def execute(self, *, spec, input, context, runtime):
        self.calls.append({"spec_id": spec.base.id, "input": input})
        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output=self._output,
        )


class FailAdapter:
    """总是失败的 adapter。"""

    async def execute(self, *, spec, input, context, runtime):
        return CapabilityResult(
            status=CapabilityStatus.FAILED,
            error="adapter failed",
        )


class ExceptionAdapter:
    """抛异常的 adapter。"""

    async def execute(self, *, spec, input, context, runtime):
        raise RuntimeError("unexpected boom")


def _make_agent(id: str) -> AgentSpec:
    return AgentSpec(
        base=CapabilitySpec(id=id, kind=CapabilityKind.AGENT, name=id),
    )


@pytest.mark.asyncio
async def test_run_dispatches_to_adapter():
    rt = CapabilityRuntime()
    adapter = MockAdapter(output="hello")
    rt.set_adapter(CapabilityKind.AGENT, adapter)
    rt.register(_make_agent("A"))

    result = await rt.run("A", input={"x": 1})

    assert result.status == CapabilityStatus.SUCCESS
    assert result.output == "hello"
    assert result.duration_ms is not None
    assert result.duration_ms > 0
    assert len(adapter.calls) == 1
    assert adapter.calls[0]["spec_id"] == "A"
    assert adapter.calls[0]["input"] == {"x": 1}


@pytest.mark.asyncio
async def test_run_not_found():
    rt = CapabilityRuntime()
    result = await rt.run("nonexistent")
    assert result.status == CapabilityStatus.FAILED
    assert "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_run_no_adapter():
    rt = CapabilityRuntime()
    rt.register(_make_agent("A"))
    result = await rt.run("A")
    assert result.status == CapabilityStatus.FAILED
    assert "no adapter" in result.error.lower()


@pytest.mark.asyncio
async def test_run_adapter_exception():
    rt = CapabilityRuntime()
    rt.set_adapter(CapabilityKind.AGENT, ExceptionAdapter())
    rt.register(_make_agent("A"))

    result = await rt.run("A")
    assert result.status == CapabilityStatus.FAILED
    assert "unexpected boom" in result.error


@pytest.mark.asyncio
async def test_run_recursion_limit():
    """模拟递归超限：adapter 内递归调用 runtime._execute。"""

    class RecursiveAdapter:
        async def execute(self, *, spec, input, context, runtime):
            return await runtime._execute(spec, input=input, context=context)

    rt = CapabilityRuntime(config=RuntimeConfig(max_depth=3))
    rt.set_adapter(CapabilityKind.AGENT, RecursiveAdapter())
    rt.register(_make_agent("A"))

    result = await rt.run("A")
    assert result.status == CapabilityStatus.FAILED
    assert "recursion" in result.error.lower() or "depth" in result.error.lower()


@pytest.mark.asyncio
async def test_register_many():
    rt = CapabilityRuntime()
    rt.register_many([_make_agent("A"), _make_agent("B")])
    assert rt.registry.has("A")
    assert rt.registry.has("B")


@pytest.mark.asyncio
async def test_validate():
    rt = CapabilityRuntime()
    rt.register(
        AgentSpec(
            base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
            collaborators=[CapabilityRef(id="missing-collaborator")],
        )
    )
    missing = rt.validate()
    assert "missing-collaborator" in missing


@pytest.mark.asyncio
async def test_run_with_custom_run_id():
    rt = CapabilityRuntime()
    adapter = MockAdapter()
    rt.set_adapter(CapabilityKind.AGENT, adapter)
    rt.register(_make_agent("A"))

    result = await rt.run("A", run_id="my-run-123")
    assert result.status == CapabilityStatus.SUCCESS


@pytest.mark.asyncio
async def test_guards_reset_each_run():
    """确保每次 run 重置全局守卫。"""
    rt = CapabilityRuntime(config=RuntimeConfig(max_total_loop_iterations=10))

    class TickAdapter:
        async def execute(self, *, spec, input, context, runtime):
            for _ in range(5):
                runtime.guards.tick()
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output="ok")

    rt.set_adapter(CapabilityKind.AGENT, TickAdapter())
    rt.register(_make_agent("A"))

    r1 = await rt.run("A")
    assert r1.status == CapabilityStatus.SUCCESS
    assert rt.guards.counter == 5

    r2 = await rt.run("A")
    assert r2.status == CapabilityStatus.SUCCESS
    assert rt.guards.counter == 5
