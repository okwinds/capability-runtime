"""
runtime/guards.py

执行守卫：全局循环熔断（防止无限循环/资源耗尽）。
"""

from __future__ import annotations


class LoopBreakerError(Exception):
    """循环熔断错误（全局循环总次数超限）。"""


class ExecutionGuards:
    """
    执行守卫。

    参数：
    - max_total_loop_iterations：全局循环总次数上限（默认 5000）。
    """

    def __init__(self, *, max_total_loop_iterations: int = 5000) -> None:
        """创建守卫实例。"""

        self.max_total_loop_iterations = int(max_total_loop_iterations)
        self._loop_iterations = 0

    def record_loop_iteration(self) -> None:
        """
        记录一次循环迭代并检查是否超限。

        异常：
        - LoopBreakerError：当迭代次数超过 max_total_loop_iterations
        """

        self._loop_iterations += 1
        if self._loop_iterations > self.max_total_loop_iterations:
            raise LoopBreakerError(
                f"total loop iterations {self._loop_iterations} > max_total_loop_iterations {self.max_total_loop_iterations}"
            )

