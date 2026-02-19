"""
adapters/workflow_adapter.py

WorkflowAdapter：编排执行 WorkflowSpec（Step / Loop / Parallel / Conditional）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..protocol.capability import CapabilityResult, CapabilityStatus
from ..protocol.context import ExecutionContext
from ..protocol.workflow import (
    ConditionalStep,
    InputMapping,
    LoopStep,
    ParallelStep,
    Step,
    WorkflowSpec,
    WorkflowStep,
)


class WorkflowAdapter:
    """Workflow 编排执行器。"""

    async def execute(  # noqa: PLR0913 - 参数显式化是契约的一部分
        self,
        *,
        spec: WorkflowSpec,
        input: dict[str, Any],
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """
        执行 Workflow。

        参数：
        - spec：WorkflowSpec
        - input：输入 dict（会合并到 context.bag）
        - context：ExecutionContext
        - runtime：CapabilityRuntime（必须提供 `_execute()` 与 `loop_controller`、`config.max_loop_iterations`）
        """

        if input:
            context.bag.update(dict(input))

        last_step_id: str | None = None
        for step in spec.steps:
            last_step_id = getattr(step, "id", None)
            res = await self._execute_step(step=step, context=context, runtime=runtime)
            if res.status != CapabilityStatus.SUCCESS:
                return res
            if last_step_id:
                context.step_outputs[last_step_id] = res.output

        if spec.output_mappings:
            final_out: dict[str, Any] = {}
            for m in spec.output_mappings:
                final_out[m.target_field] = context.resolve_mapping(m.source)
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output=final_out)

        if last_step_id and last_step_id in context.step_outputs:
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output=context.step_outputs[last_step_id])
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output={})

    async def _execute_step(self, *, step: WorkflowStep, context: ExecutionContext, runtime: Any) -> CapabilityResult:
        """
        执行单个 WorkflowStep（递归）。

        参数：
        - step：WorkflowStep
        - context：ExecutionContext
        - runtime：CapabilityRuntime
        """

        if isinstance(step, Step):
            step_input = _build_input_from_mappings(mappings=step.input_mappings, context=context)
            return await runtime._execute(capability_id=step.capability.id, input=step_input, context=context)

        if isinstance(step, LoopStep):
            async def _executor(cap_id: str, input_dict: dict[str, Any], ctx: ExecutionContext) -> CapabilityResult:
                return await runtime._execute(capability_id=cap_id, input=input_dict, context=ctx)

            return await runtime.loop_controller.execute_loop(
                step=step,
                context=context,
                executor=_executor,
                global_max_iterations=int(getattr(runtime.config, "max_loop_iterations", 200)),
            )

        if isinstance(step, ParallelStep):
            branch_tasks = [self._execute_step(step=b, context=context, runtime=runtime) for b in step.branches]
            results = await asyncio.gather(*branch_tasks, return_exceptions=False)
            return _join_parallel(step=step, results=results)

        if isinstance(step, ConditionalStep):
            cond_val = context.resolve_mapping(step.condition_source)
            key = "" if cond_val is None else str(cond_val)
            chosen = step.branches.get(key) or step.default
            if chosen is None:
                return CapabilityResult(status=CapabilityStatus.FAILED, error=f"no conditional branch matched: {key!r}")
            return await self._execute_step(step=chosen, context=context, runtime=runtime)

        return CapabilityResult(status=CapabilityStatus.FAILED, error=f"unknown WorkflowStep: {type(step).__name__}")


def _build_input_from_mappings(*, mappings: list[InputMapping], context: ExecutionContext) -> dict[str, Any]:
    """
    根据 InputMapping 列表生成输入 dict。

    参数：
    - mappings：映射列表
    - context：ExecutionContext
    """

    out: dict[str, Any] = {}
    for m in mappings:
        out[m.target_field] = context.resolve_mapping(m.source)
    return out


def _join_parallel(*, step: ParallelStep, results: list[CapabilityResult]) -> CapabilityResult:
    """
    并行 join 策略（最小可回归语义）。

    参数：
    - step：ParallelStep（含 join_strategy）
    - results：分支结果列表（与 step.branches 同序）
    """

    strategy = (step.join_strategy or "all_success").strip()
    any_success = any(r.status == CapabilityStatus.SUCCESS for r in results)
    all_success = all(r.status == CapabilityStatus.SUCCESS for r in results)

    if strategy == "all_success":
        if not all_success:
            return CapabilityResult(status=CapabilityStatus.FAILED, error="parallel join all_success failed", output={"results": [r.output for r in results]})
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"results": [r.output for r in results]})

    if strategy == "any_success":
        if not any_success:
            return CapabilityResult(status=CapabilityStatus.FAILED, error="parallel join any_success failed", output={"results": [r.output for r in results]})
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"results": [r.output for r in results]})

    if strategy == "best_effort":
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"results": [r.output for r in results]})

    return CapabilityResult(status=CapabilityStatus.FAILED, error=f"unknown join_strategy: {strategy!r}")

