"""ExecutionGuards 单元测试。"""
from __future__ import annotations

import pytest

from capability_runtime.guards import ExecutionGuards, LoopBreakerError


def test_tick_increments_counter():
    g = ExecutionGuards(max_total_loop_iterations=100)
    g.tick()
    g.tick()
    g.tick()
    assert g.counter == 3


def test_tick_at_limit():
    g = ExecutionGuards(max_total_loop_iterations=3)
    g.tick()  # 1
    g.tick()  # 2
    g.tick()  # 3 -- 恰好等于上限，不应抛异常
    assert g.counter == 3


def test_tick_exceeds_limit():
    g = ExecutionGuards(max_total_loop_iterations=3)
    g.tick()
    g.tick()
    g.tick()
    with pytest.raises(LoopBreakerError, match="limit.*3.*exceeded"):
        g.tick()  # 4 -- 超限


def test_reset():
    g = ExecutionGuards(max_total_loop_iterations=5)
    g.tick()
    g.tick()
    assert g.counter == 2
    g.reset()
    assert g.counter == 0
    g.tick()
    assert g.counter == 1


@pytest.mark.asyncio
async def test_run_loop_rejects_non_list_items() -> None:
    """
    回归护栏：`run_loop` 必须在入口验证 `items` 类型。

    约束：
    - 若 `items` 不是 list，必须返回 FAILED（error_code=INVALID_LOOP_INPUT）。
    - 这是防御性编程，避免后续 `len(items)` 或迭代时抛 TypeError。
    """
    from capability_runtime.protocol.capability import CapabilityStatus

    g = ExecutionGuards(max_total_loop_iterations=100)

    async def execute(item, idx):  # type: ignore[no-untyped-def]
        return CapabilityStatus.SUCCESS

    # 测试 dict（常见误用）
    result = await g.run_loop(
        items={"a": 1, "b": 2},  # type: ignore[arg-type]
        max_iterations=10,
        execute_fn=execute,
    )
    assert result.status == CapabilityStatus.FAILED
    assert result.error_code == "INVALID_LOOP_INPUT"
    assert "dict" in (result.error or "")

    # 测试 tuple（用户可能误用）
    result = await g.run_loop(
        items=(1, 2, 3),  # type: ignore[arg-type]
        max_iterations=10,
        execute_fn=execute,
    )
    assert result.status == CapabilityStatus.FAILED
    assert result.error_code == "INVALID_LOOP_INPUT"
    assert "tuple" in (result.error or "")

    # 测试 None
    result = await g.run_loop(
        items=None,  # type: ignore[arg-type]
        max_iterations=10,
        execute_fn=execute,
    )
    assert result.status == CapabilityStatus.FAILED
    assert result.error_code == "INVALID_LOOP_INPUT"

