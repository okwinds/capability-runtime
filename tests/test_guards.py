"""ExecutionGuards 单元测试。"""
from __future__ import annotations

import pytest

from agently_skills_runtime.guards import ExecutionGuards, LoopBreakerError


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

