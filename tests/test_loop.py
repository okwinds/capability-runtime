"""LoopController 单元测试。"""
from __future__ import annotations

import pytest

from capability_runtime.protocol.capability import CapabilityResult, CapabilityStatus
from capability_runtime.guards import ExecutionGuards, LoopBreakerError
from capability_runtime.types import NodeReport


def _report(run_id: str) -> NodeReport:
    return NodeReport(
        status="failed",
        reason="workflow_step_failed",
        completion_reason="loop_iteration_failed",
        engine={"name": "skills-runtime-sdk-python", "module": "skills_runtime", "version": "0"},
        bridge={"name": "capability-runtime", "version": "0"},
        run_id=run_id,
        events_path=f"/tmp/{run_id}.jsonl",
        activated_skills=[],
        tool_calls=[],
        artifacts=[],
        meta={},
    )


@pytest.fixture
def guards():
    return ExecutionGuards(max_total_loop_iterations=1000)


@pytest.mark.asyncio
async def test_normal_loop(guards):
    async def execute(item, idx):
        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output=f"processed-{item}",
        )

    result = await guards.run_loop(
        items=["a", "b", "c"],
        max_iterations=10,
        execute_fn=execute,
    )
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output == ["processed-a", "processed-b", "processed-c"]
    assert result.metadata["completed_iterations"] == 3


@pytest.mark.asyncio
async def test_max_iterations_limits_items(guards):
    async def execute(item, idx):
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=item)

    result = await guards.run_loop(
        items=[1, 2, 3, 4, 5],
        max_iterations=3,
        execute_fn=execute,
    )
    assert result.output == [1, 2, 3]
    assert result.metadata["completed_iterations"] == 3
    assert result.metadata["total_planned"] == 3


@pytest.mark.asyncio
async def test_abort_on_failure(guards):
    async def execute(item, idx):
        if idx == 1:
            report = _report("loop-abort")
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error="bad item",
                error_code="STEP_TIMEOUT",
                report=report,
                node_report=report,
            )
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=item)

    result = await guards.run_loop(
        items=["a", "b", "c"],
        max_iterations=10,
        execute_fn=execute,
        fail_strategy="abort",
    )
    assert result.status == CapabilityStatus.FAILED
    assert "aborted at iteration 1" in result.error.lower()
    assert result.output == ["a"]
    assert result.error_code == "STEP_TIMEOUT"
    assert result.node_report is not None
    assert result.node_report.reason == "workflow_step_failed"


@pytest.mark.asyncio
async def test_abort_on_pending(guards):
    async def execute(item, idx):
        if idx == 1:
            return CapabilityResult(status=CapabilityStatus.PENDING, output=None)
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=item)

    result = await guards.run_loop(
        items=["a", "b", "c"],
        max_iterations=10,
        execute_fn=execute,
        fail_strategy="abort",
    )
    assert result.status == CapabilityStatus.PENDING
    assert result.output == ["a"]
    assert result.metadata["completed_iterations"] == 1


@pytest.mark.asyncio
async def test_abort_on_cancelled_preserves_error_code_and_node_report(guards):
    async def execute(item, idx):
        if idx == 1:
            report = NodeReport(
                status="incomplete",
                reason="cancelled",
                completion_reason="run_cancelled",
                engine={"name": "skills-runtime-sdk-python", "module": "skills_runtime", "version": "0"},
                bridge={"name": "capability-runtime", "version": "0"},
                run_id="loop-cancelled",
                events_path="/tmp/loop-cancelled.jsonl",
                activated_skills=[],
                tool_calls=[],
                artifacts=[],
                meta={},
            )
            return CapabilityResult(
                status=CapabilityStatus.CANCELLED,
                error="execution cancelled",
                error_code="RUN_CANCELLED",
                report=report,
                node_report=report,
            )
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=item)

    result = await guards.run_loop(
        items=["a", "b", "c"],
        max_iterations=10,
        execute_fn=execute,
        fail_strategy="abort",
    )
    assert result.status == CapabilityStatus.CANCELLED
    assert result.output == ["a"]
    assert result.error == "execution cancelled"
    assert result.error_code == "RUN_CANCELLED"
    assert result.node_report is not None
    assert result.node_report.reason == "cancelled"
    assert result.metadata["completed_iterations"] == 1


@pytest.mark.asyncio
async def test_skip_on_failure(guards):
    async def execute(item, idx):
        if idx == 1:
            return CapabilityResult(status=CapabilityStatus.FAILED, error="skip me")
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=item)

    result = await guards.run_loop(
        items=["a", "b", "c"],
        max_iterations=10,
        execute_fn=execute,
        fail_strategy="skip",
    )
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output == ["a", "c"]
    assert len(result.metadata["skipped_errors"]) == 1


@pytest.mark.asyncio
async def test_collect_on_failure(guards):
    async def execute(item, idx):
        if idx == 1:
            return CapabilityResult(status=CapabilityStatus.FAILED, error="collected")
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=item)

    result = await guards.run_loop(
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
async def test_exception_in_execute_fn(guards):
    async def execute(item, idx):
        raise ValueError("boom")

    result = await guards.run_loop(
        items=["a"],
        max_iterations=10,
        execute_fn=execute,
        fail_strategy="abort",
    )
    assert result.status == CapabilityStatus.FAILED
    assert "exception" in result.error.lower()
    assert result.error_code == "ENGINE_ERROR"


@pytest.mark.asyncio
async def test_global_guards_breaker():
    guards = ExecutionGuards(max_total_loop_iterations=2)

    async def execute(item, idx):
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=item)

    with pytest.raises(LoopBreakerError):
        await guards.run_loop(
            items=["a", "b", "c"],
            max_iterations=10,
            execute_fn=execute,
        )


@pytest.mark.asyncio
async def test_empty_items(guards):
    async def execute(item, idx):
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=item)

    result = await guards.run_loop(
        items=[],
        max_iterations=10,
        execute_fn=execute,
    )
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output == []
