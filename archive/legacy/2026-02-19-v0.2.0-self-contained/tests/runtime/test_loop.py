from __future__ import annotations

import pytest

from capability_runtime.protocol.capability import CapabilityResult, CapabilityStatus
from capability_runtime.protocol.context import ExecutionContext
from capability_runtime.protocol.capability import CapabilityRef
from capability_runtime.protocol.workflow import InputMapping, LoopStep
from capability_runtime.runtime.guards import ExecutionGuards
from capability_runtime.runtime.loop import LoopController


@pytest.mark.asyncio
async def test_loop_success_collects_outputs() -> None:
    guards = ExecutionGuards(max_total_loop_iterations=100)
    lc = LoopController(guards=guards)
    ctx = ExecutionContext(run_id="r", bag={"items": [{"x": 1}, {"x": 2}]})
    step = LoopStep(
        id="loop",
        capability=CapabilityRef(id="cap"),
        iterate_over="context.items",
        item_input_mappings=[InputMapping(source="item.x", target_field="x")],
        collect_as="results",
        max_iterations=10,
    )

    async def exec_cap(cap_id: str, input: dict, context: ExecutionContext) -> CapabilityResult:
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=input["x"])

    res = await lc.execute_loop(step=step, context=ctx, executor=exec_cap, global_max_iterations=10)
    assert res.status == CapabilityStatus.SUCCESS
    assert res.output == {"results": [1, 2]}


@pytest.mark.asyncio
async def test_loop_max_iterations_fail() -> None:
    guards = ExecutionGuards(max_total_loop_iterations=100)
    lc = LoopController(guards=guards)
    ctx = ExecutionContext(run_id="r", bag={"items": [1, 2, 3]})
    step = LoopStep(id="loop", capability=CapabilityRef(id="cap"), iterate_over="context.items", max_iterations=2)

    async def exec_cap(cap_id: str, input: dict, context: ExecutionContext) -> CapabilityResult:
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=1)

    res = await lc.execute_loop(step=step, context=ctx, executor=exec_cap, global_max_iterations=100)
    assert res.status == CapabilityStatus.FAILED


@pytest.mark.asyncio
async def test_loop_iteration_failure_returns_partial() -> None:
    guards = ExecutionGuards(max_total_loop_iterations=100)
    lc = LoopController(guards=guards)
    ctx = ExecutionContext(run_id="r", bag={"items": [{"x": 1}, {"x": 2}]})
    step = LoopStep(
        id="loop",
        capability=CapabilityRef(id="cap"),
        iterate_over="context.items",
        item_input_mappings=[InputMapping(source="item.x", target_field="x")],
    )

    async def exec_cap(cap_id: str, input: dict, context: ExecutionContext) -> CapabilityResult:
        if input["x"] == 2:
            return CapabilityResult(status=CapabilityStatus.FAILED, error="boom")
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=input["x"])

    res = await lc.execute_loop(step=step, context=ctx, executor=exec_cap, global_max_iterations=100)
    assert res.status == CapabilityStatus.FAILED
    assert res.output["failed_at"] == 1
    assert res.output["partial_results"] == [1]
