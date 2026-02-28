"""执行守卫——全局循环和递归保护。"""
from __future__ import annotations


class LoopBreakerError(Exception):
    """全局循环迭代次数超限。"""


class ExecutionGuards:
    """
    全局执行守卫。

    作用：防止全局范围内的循环迭代总次数超限。
    这是 LoopStep.max_iterations 之上的第二道防线。
    """

    def __init__(self, *, max_total_loop_iterations: int = 50000):
        self._max = max_total_loop_iterations
        self._counter = 0

    def tick(self) -> None:
        """每次循环迭代调用一次。超限抛 LoopBreakerError。"""
        self._counter += 1
        if self._counter > self._max:
            raise LoopBreakerError(
                f"Global loop iteration limit ({self._max}) exceeded. "
                f"Total iterations so far: {self._counter}"
            )

    @property
    def counter(self) -> int:
        """当前累计迭代次数。"""
        return self._counter

    def reset(self) -> None:
        """重置计数器（通常在新的顶层 run 时调用）。"""
        self._counter = 0

