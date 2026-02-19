from __future__ import annotations

import pytest

from agently_skills_runtime.runtime.guards import ExecutionGuards, LoopBreakerError


def test_loop_breaker_error() -> None:
    guards = ExecutionGuards(max_total_loop_iterations=2)
    guards.record_loop_iteration()
    guards.record_loop_iteration()
    with pytest.raises(LoopBreakerError):
        guards.record_loop_iteration()

