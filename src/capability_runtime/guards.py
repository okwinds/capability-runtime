"""执行守卫——全局循环与编排保护。"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Awaitable, Callable, Dict, List

from .protocol.capability import CapabilityResult, CapabilityStatus


class LoopBreakerError(Exception):
    """全局循环迭代次数超限。"""


class ExecutionGuards:
    """
    全局执行守卫（per-run）。

    职责：
    - 维护“全局循环迭代次数”计数器，用于熔断失控的 Loop；
    - 提供 LoopStep 的确定性执行方法（`run_loop`），并在每次迭代调用 `tick()`。

    说明：
    - 该守卫是 `LoopStep.max_iterations` 之上的第二道防线；
    - 调用方应在每次顶层 run 开始前调用 `reset()`，避免跨 run 串扰。
    """

    def __init__(self, *, max_total_loop_iterations: int = 50000):
        self._max = max_total_loop_iterations
        self._counter = 0

    def tick(self) -> None:
        """
        记录一次循环迭代。

        超过全局上限时抛出 LoopBreakerError（fail-fast）。
        """

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

    async def run_loop(
        self,
        *,
        items: List[Any],
        max_iterations: int,
        execute_fn: Callable[[Any, int], Awaitable[CapabilityResult]],
        fail_strategy: str = "abort",
    ) -> CapabilityResult:
        """
        执行 LoopStep 语义（确定性）。

        参数：
        - items：要遍历的集合
        - max_iterations：最多迭代次数（在 items 长度之上取 min）
        - execute_fn：执行函数，签名为 `(item, index) -> CapabilityResult`
        - fail_strategy："abort" | "skip" | "collect"

        返回：
        - CapabilityResult，其中 output 为结果列表；metadata 提供 completed/total/skipped 等摘要。
        """

        results: List[Any] = []
        errors: List[Dict[str, Any]] = []
        effective_max = min(max_iterations, len(items))

        for idx, item in enumerate(items[:effective_max]):
            self.tick()

            try:
                result = await execute_fn(item, idx)
            except Exception as exc:
                result = CapabilityResult(
                    status=CapabilityStatus.FAILED,
                    error=f"Loop iteration {idx} exception: {exc}",
                    error_code="ENGINE_ERROR",
                    metadata={"exception_type": type(exc).__name__},
                )

            if result.status != CapabilityStatus.SUCCESS:
                # LoopStep 内部一旦出现非 success：
                # - FAILED：按 fail_strategy 处理（abort/skip/collect）
                # - PENDING/RUNNING/CANCELLED：不应被当作成功继续推进（否则会吞掉 needs_approval/incomplete 等语义）
                if result.status in (CapabilityStatus.PENDING, CapabilityStatus.RUNNING, CapabilityStatus.CANCELLED):
                    return CapabilityResult(
                        status=result.status,
                        output=results,
                        error=result.error,
                        report=result.report,
                        node_report=result.node_report,
                        metadata={
                            "completed_iterations": idx,
                            "total_planned": effective_max,
                            "aborted_status": getattr(result.status, "value", str(result.status)),
                        },
                    )

                if fail_strategy == "abort":
                    return replace(
                        result,
                        output=results,
                        error=f"Loop aborted at iteration {idx}/{effective_max}: {result.error}",
                        metadata={
                            **dict(getattr(result, "metadata", {}) or {}),
                            "completed_iterations": idx,
                            "total_planned": effective_max,
                        },
                    )
                if fail_strategy == "skip":
                    errors.append({"index": idx, "error": result.error})
                    continue
                if fail_strategy == "collect":
                    results.append({"status": "failed", "error": result.error, "index": idx})
                    continue

            results.append(result.output)

        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output=results,
            metadata={
                "completed_iterations": len(results),
                "total_planned": effective_max,
                "skipped_errors": errors if errors else None,
            },
        )
