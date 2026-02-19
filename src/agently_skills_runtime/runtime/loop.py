"""
runtime/loop.py

循环控制器：执行 LoopStep，并负责步骤级/全局双重限制与 partial results 语义。
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from ..protocol.capability import CapabilityResult, CapabilityStatus
from ..protocol.context import ExecutionContext
from ..protocol.workflow import InputMapping, LoopStep
from .guards import ExecutionGuards, LoopBreakerError

LoopExecutor = Callable[[str, dict[str, Any], ExecutionContext], Awaitable[CapabilityResult]]


class LoopController:
    """
    循环控制器。

    参数：
    - guards：ExecutionGuards（全局循环熔断）。
    """

    def __init__(self, *, guards: ExecutionGuards) -> None:
        """创建 LoopController。"""

        self._guards = guards

    async def execute_loop(
        self,
        *,
        step: LoopStep,
        context: ExecutionContext,
        executor: LoopExecutor,
        global_max_iterations: int,
    ) -> CapabilityResult:
        """
        执行循环步骤。

        参数：
        - step：LoopStep
        - context：ExecutionContext（会被注入 __loop_item__/__loop_index__）
        - executor：执行器（用于调用被循环的 capability）
        - global_max_iterations：全局循环上限（RuntimeConfig.max_loop_iterations）

        返回：
        - CapabilityResult：成功时 output={collect_as:[...]}；失败时 output 包含 partial_results/failed_at。
        """

        try:
            items = context.resolve_mapping(step.iterate_over)
        except Exception as exc:
            return CapabilityResult(status=CapabilityStatus.FAILED, error=f"iterate_over resolve failed: {exc}")

        if items is None:
            return CapabilityResult(status=CapabilityStatus.FAILED, error="iterate_over resolved to None")
        if not isinstance(items, (list, tuple)):
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"iterate_over must resolve to list/tuple, got {type(items).__name__}",
            )

        max_items = min(int(step.max_iterations), int(global_max_iterations))
        if len(items) > max_items:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"loop items {len(items)} > max_items {max_items}",
                output={"failed_at": 0, "partial_results": []},
            )

        collected: list[Any] = []
        for idx, item in enumerate(items):
            try:
                self._guards.record_loop_iteration()
            except LoopBreakerError as exc:
                return CapabilityResult(
                    status=CapabilityStatus.FAILED,
                    error=str(exc),
                    output={"failed_at": idx, "partial_results": collected},
                )

            context.bag["__loop_item__"] = item
            context.bag["__loop_index__"] = idx

            input_dict = _build_input_from_mappings(mappings=step.item_input_mappings, context=context)
            result = await executor(step.capability.id, input_dict, context)

            if result.status != CapabilityStatus.SUCCESS:
                return CapabilityResult(
                    status=CapabilityStatus.FAILED,
                    error=result.error or "loop iteration failed",
                    output={"failed_at": idx, "partial_results": collected},
                )

            collected.append(result.output)

        return CapabilityResult(status=CapabilityStatus.SUCCESS, output={step.collect_as: collected})


def _build_input_from_mappings(*, mappings: list[InputMapping], context: ExecutionContext) -> dict[str, Any]:
    """
    根据 InputMapping 列表生成输入 dict。

    参数：
    - mappings：InputMapping 列表
    - context：ExecutionContext（用于 resolve_mapping）

    返回：
    - input dict
    """

    out: dict[str, Any] = {}
    for m in mappings:
        out[m.target_field] = context.resolve_mapping(m.source)
    return out

