"""LoopController 单元测试。"""
from __future__ import annotations

import pytest

from agently_skills_runtime.protocol.capability import CapabilityResult, CapabilityStatus
from agently_skills_runtime.runtime.guards import ExecutionGuards, LoopBreakerError
from agently_skills_runtime.runtime.loop import LoopController


@pytest.fixture
def guards():
    return ExecutionGuards(max_total_loop_iterations=1000)


@pytest.fixture
def controller(guards):
    return LoopController(guards=guards)


@pytest.mark.asyncio
async def test_normal_loop(controller):
    async def execute(item, idx):
        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output=f"processed-{item}",
        )

    result = await controller.run_loop(
        items=["a", "b", "c"],
        max_iterations=10,
        execute_fn=execute,
    )
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output == ["processed-a", "processed-b", "processed-c"]
    assert result.metadata["completed_iterations"] == 3


@pytest.mark.asyncio
async def test_max_iterations_limits_items(controller):
    async def execute(item, idx):
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=item)

    result = await controller.run_loop(
        items=[1, 2, 3, 4, 5],
        max_iterations=3,
        execute_fn=execute,
    )
    assert result.output == [1, 2, 3]
    assert result.metadata["completed_iterations"] == 3
    assert result.metadata["total_planned"] == 3


@pytest.mark.asyncio
async def test_abort_on_failure(controller):
    async def execute(item, idx):
        if idx == 1:
            return CapabilityResult(status=CapabilityStatus.FAILED, error="bad item")
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=item)

    result = await controller.run_loop(
        items=["a", "b", "c"],
        max_iterations=10,
        execute_fn=execute,
        fail_strategy="abort",
    )
    assert result.status == CapabilityStatus.FAILED
    assert "aborted at iteration 1" in result.error.lower()
    assert result.output == ["a"]


@pytest.mark.asyncio
async def test_skip_on_failure(controller):
    async def execute(item, idx):
        if idx == 1:
            return CapabilityResult(status=CapabilityStatus.FAILED, error="skip me")
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=item)

    result = await controller.run_loop(
        items=["a", "b", "c"],
        max_iterations=10,
        execute_fn=execute,
        fail_strategy="skip",
    )
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output == ["a", "c"]
    assert len(result.metadata["skipped_errors"]) == 1


@pytest.mark.asyncio
async def test_collect_on_failure(controller):
    async def execute(item, idx):
        if idx == 1:
            return CapabilityResult(status=CapabilityStatus.FAILED, error="collected")
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=item)

    result = await controller.run_loop(
        items=["a", "b", "c"],
        max_iterations=10,
        execute_fn=execute,
        fail_strategy="collect",
    )
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output[0] == "a"
    assert result.output[1]["status"] == "failed"
    assert result.output[2] == "c"


@pytest.mark.asyncio
async def test_exception_in_execute_fn(controller):
    async def execute(item, idx):
        raise ValueError("boom")

    result = await controller.run_loop(
        items=["a"],
        max_iterations=10,
        execute_fn=execute,
        fail_strategy="abort",
    )
    assert result.status == CapabilityStatus.FAILED
    assert "exception" in result.error.lower()


@pytest.mark.asyncio
async def test_global_guards_breaker():
    guards = ExecutionGuards(max_total_loop_iterations=2)
    controller = LoopController(guards=guards)

    async def execute(item, idx):
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=item)

    with pytest.raises(LoopBreakerError):
        await controller.run_loop(
            items=["a", "b", "c"],
            max_iterations=10,
            execute_fn=execute,
        )


@pytest.mark.asyncio
async def test_empty_items(controller):
    async def execute(item, idx):
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=item)

    result = await controller.run_loop(
        items=[],
        max_iterations=10,
        execute_fn=execute,
    )
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output == []

