"""循环控制器——封装 LoopStep 的执行逻辑。"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List

from ..protocol.capability import CapabilityResult, CapabilityStatus
from .guards import ExecutionGuards


class LoopController:
    """
    循环控制器。

    职责：
    - 遍历集合，对每个元素调用 execute_fn
    - 尊重 max_iterations 限制
    - 每次迭代调用 guards.tick()（全局熔断）
    - 根据 fail_strategy 决定失败时的行为
    """

    def __init__(self, *, guards: ExecutionGuards):
        self._guards = guards

    async def run_loop(
        self,
        *,
        items: List[Any],
        max_iterations: int,
        execute_fn: Callable[[Any, int], Awaitable[CapabilityResult]],
        fail_strategy: str = "abort",
    ) -> CapabilityResult:
        """
        执行循环。

        参数：
        - items: 要遍历的集合
        - max_iterations: 最大迭代次数
        - execute_fn: 执行函数，签名 (item, index) -> CapabilityResult
        - fail_strategy: "abort" | "skip" | "collect"

        返回：CapabilityResult，output 为结果列表
        """
        results: List[Any] = []
        errors: List[Dict[str, Any]] = []
        effective_max = min(max_iterations, len(items))

        for idx, item in enumerate(items[:effective_max]):
            self._guards.tick()

            try:
                result = await execute_fn(item, idx)
            except Exception as exc:
                result = CapabilityResult(
                    status=CapabilityStatus.FAILED,
                    error=f"Loop iteration {idx} exception: {exc}",
                )

            if result.status == CapabilityStatus.FAILED:
                if fail_strategy == "abort":
                    return CapabilityResult(
                        status=CapabilityStatus.FAILED,
                        output=results,
                        error=f"Loop aborted at iteration {idx}/{effective_max}: {result.error}",
                        metadata={
                            "completed_iterations": idx,
                            "total_planned": effective_max,
                        },
                    )
                if fail_strategy == "skip":
                    errors.append({"index": idx, "error": result.error})
                    continue
                if fail_strategy == "collect":
                    results.append(
                        {"status": "failed", "error": result.error, "index": idx}
                    )
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

