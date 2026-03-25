from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from types import MappingProxyType

import pytest

from capability_runtime.protocol.capability import CapabilityKind, CapabilityRef, CapabilityResult, CapabilitySpec, CapabilityStatus
from capability_runtime.protocol.context import CancellationToken, ExecutionContext
from capability_runtime.protocol.agent import AgentSpec
from capability_runtime.protocol.workflow import LoopStep, Step
from capability_runtime.registry import CapabilityRegistry
from capability_runtime.guards import ExecutionGuards
from capability_runtime.types import NodeReport

from capability_runtime.adapters.triggerflow_workflow_engine import TriggerFlowWorkflowEngine


class _FakeServices:
    def __init__(self, *, registry: CapabilityRegistry) -> None:
        self.registry = registry
        self.calls: List[Dict[str, Any]] = []

    async def execute_capability(
        self, *, spec: Any, input: Dict[str, Any], context: ExecutionContext
    ) -> CapabilityResult:
        self.calls.append({"spec_id": spec.base.id, "input": dict(input), "run_id": context.run_id})
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"ok": True, "spec_id": spec.base.id})

    def build_fail_closed_report(
        self,
        *,
        run_id: str,
        status: str,
        reason: Optional[str],
        completion_reason: str,
        meta: Dict[str, Any],
    ) -> NodeReport:
        """构造 fail-closed NodeReport（测试用最小实现）。"""
        return NodeReport(
            status=status,  # type: ignore[arg-type]
            reason=reason,
            completion_reason=completion_reason,
            run_id=run_id,
            engine={"name": "test", "module": "test"},
            bridge={"name": "test"},
            meta=meta,
        )


@pytest.mark.asyncio
async def test_triggerflow_engine_uses_services_registry_and_execute_capability() -> None:
    registry = CapabilityRegistry()
    registry.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    services = _FakeServices(registry=registry)

    ctx = ExecutionContext(run_id="r1")
    engine = TriggerFlowWorkflowEngine()
    result = await engine._execute_basic_step(
        Step(id="s1", capability=CapabilityRef(id="A")),
        context=ctx,
        services=services,  # type: ignore[arg-type]
    )

    assert result.status == CapabilityStatus.SUCCESS
    assert services.calls and services.calls[0]["spec_id"] == "A"
    assert ctx.step_outputs["s1"]["spec_id"] == "A"


@pytest.mark.asyncio
async def test_cancellation_token_short_circuits_step_execution() -> None:
    registry = CapabilityRegistry()
    registry.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))

    class _NoCallServices(_FakeServices):
        async def execute_capability(self, *, spec: Any, input: Dict[str, Any], context: ExecutionContext) -> CapabilityResult:
            raise AssertionError("execute_capability should not be called when cancelled")

    token = CancellationToken()
    token.cancel()
    ctx = ExecutionContext(run_id="r1", cancel_token=token)
    engine = TriggerFlowWorkflowEngine()
    services = _NoCallServices(registry=registry)

    result = await engine._execute_step(
        Step(id="s1", capability=CapabilityRef(id="A")),
        context=ctx,
        services=services,  # type: ignore[arg-type]
    )
    assert result.status == CapabilityStatus.CANCELLED
    assert result.error == "execution cancelled"


@pytest.mark.asyncio
async def test_step_timeout_returns_failed_result() -> None:
    registry = CapabilityRegistry()
    registry.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))

    class _SlowServices(_FakeServices):
        async def execute_capability(self, *, spec: Any, input: Dict[str, Any], context: ExecutionContext) -> CapabilityResult:
            await asyncio.sleep(0.05)
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"late": True})

    ctx = ExecutionContext(run_id="r1")
    engine = TriggerFlowWorkflowEngine()
    services = _SlowServices(registry=registry)

    result = await engine._execute_basic_step(
        Step(id="s1", capability=CapabilityRef(id="A"), timeout_s=0.01),
        context=ctx,
        services=services,  # type: ignore[arg-type]
    )

    assert result.status == CapabilityStatus.FAILED
    assert result.error == "step timeout: s1"


@pytest.mark.asyncio
async def test_loop_step_timeout_is_supported() -> None:
    registry = CapabilityRegistry()
    registry.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))

    class _SlowServices(_FakeServices):
        async def execute_capability(self, *, spec: Any, input: Dict[str, Any], context: ExecutionContext) -> CapabilityResult:
            await asyncio.sleep(0.05)
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"late": True})

    token: Optional[CancellationToken] = None
    ctx = ExecutionContext(
        run_id="r1",
        bag=MappingProxyType({"items": [1, 2, 3]}),
        guards=ExecutionGuards(max_total_loop_iterations=1000),
        cancel_token=token,
    )
    engine = TriggerFlowWorkflowEngine()
    services = _SlowServices(registry=registry)

    # 只断言：字段存在且超时能返回 FAILED（具体循环行为由 engine 实现决定）
    result = await engine._execute_loop_step(
        LoopStep(id="loop", capability=CapabilityRef(id="A"), iterate_over="context.items", timeout_s=0.01),
        context=ctx,
        services=services,  # type: ignore[arg-type]
    )
    assert result.status == CapabilityStatus.FAILED
    assert result.error == "loop timeout: loop"
