"""Workflow 适配器：WorkflowSpec → 步骤编排执行。"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from ..protocol.capability import CapabilityResult, CapabilityStatus
from ..protocol.context import ExecutionContext
from ..protocol.workflow import (
    ConditionalStep,
    InputMapping,
    LoopStep,
    ParallelStep,
    Step,
    WorkflowSpec,
)

def _to_step_result_dict(result: CapabilityResult) -> Dict[str, Any]:
    """把 CapabilityResult 归一为 workflow step_results 的最小可编排结构。"""

    return {
        "status": getattr(result.status, "value", str(result.status)),
        "output": result.output,
        "error": result.error,
        "report": result.report,
    }


class WorkflowAdapter:
    """
    Workflow 适配器。

    不依赖任何上游——所有执行都通过 runtime._execute() 递归回 Engine。
    """

    async def execute(
        self,
        *,
        spec: WorkflowSpec,
        input: Dict[str, Any],
        context: ExecutionContext,
        runtime: Any,  # CapabilityRuntime
    ) -> CapabilityResult:
        """
        执行 WorkflowSpec。

        流程：
        1. 合并 input 到 context bag
        2. 遍历 steps，按类型分发执行
        3. 每步结果缓存到 context.step_outputs
        4. 步骤失败 → 立即返回
        5. 全部完成 → 解析 output_mappings 构造最终输出
        """
        context.bag.update(input)

        for step in spec.steps:
            result = await self._execute_step(step, context=context, runtime=runtime)
            # Workflow 作为“编排胶水”，不应把非 success 的状态当作成功继续推进。
            # - FAILED：明确失败
            # - PENDING：needs_approval / incomplete 等需要外部介入
            # - CANCELLED：取消
            if result.status != CapabilityStatus.SUCCESS:
                return result

        output = self._resolve_output_mappings(spec.output_mappings, context)
        if output is None:
            output = dict(context.step_outputs)

        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=output)

    async def _execute_step(
        self,
        step: Any,
        *,
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """按步骤类型分发执行。"""
        if isinstance(step, Step):
            return await self._execute_basic_step(step, context=context, runtime=runtime)
        if isinstance(step, LoopStep):
            return await self._execute_loop_step(step, context=context, runtime=runtime)
        if isinstance(step, ParallelStep):
            return await self._execute_parallel_step(step, context=context, runtime=runtime)
        if isinstance(step, ConditionalStep):
            return await self._execute_conditional_step(
                step, context=context, runtime=runtime
            )
        return CapabilityResult(
            status=CapabilityStatus.FAILED,
            error=f"Unknown step type: {type(step).__name__}",
        )

    async def _execute_basic_step(
        self,
        step: Step,
        *,
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """执行基础步骤。"""
        step_input = self._resolve_input_mappings(step.input_mappings, context)

        target_spec = runtime.registry.get_or_raise(step.capability.id)
        result = await runtime._execute(target_spec, input=step_input, context=context)

        context.step_outputs[step.id] = result.output
        context.step_results[step.id] = _to_step_result_dict(result)
        return result

    async def _execute_loop_step(
        self,
        step: LoopStep,
        *,
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """执行循环步骤。"""
        items = context.resolve_mapping(step.iterate_over)
        if not isinstance(items, list):
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=(
                    f"LoopStep '{step.id}': iterate_over resolved to "
                    f"{type(items).__name__}, expected list"
                ),
            )

        target_spec = runtime.registry.get_or_raise(step.capability.id)

        async def execute_item(item: Any, idx: int) -> CapabilityResult:
            item_context = ExecutionContext(
                run_id=context.run_id,
                parent_context=context,
                depth=context.depth,
                max_depth=context.max_depth,
                bag={**context.bag, "__current_item__": item},
                step_outputs=dict(context.step_outputs),
                step_results=dict(context.step_results),
                call_chain=list(context.call_chain),
            )
            step_input = self._resolve_input_mappings(step.item_input_mappings, item_context)
            if not step_input:
                step_input = item if isinstance(item, dict) else {"item": item}
            return await runtime._execute(target_spec, input=step_input, context=item_context)

        result = await runtime.loop_controller.run_loop(
            items=items,
            max_iterations=step.max_iterations,
            execute_fn=execute_item,
            fail_strategy=step.fail_strategy,
        )

        context.step_outputs[step.id] = result.output
        context.step_results[step.id] = _to_step_result_dict(result)
        return result

    async def _execute_parallel_step(
        self,
        step: ParallelStep,
        *,
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """执行并行步骤。"""
        # 并行分支必须隔离执行上下文：
        # - 允许读取“并行之前”的 step_outputs（作为输入映射来源）
        # - 禁止把分支内部 step_outputs 泄露到父级（避免污染对外输出与产生隐式依赖）
        branch_contexts = [
            ExecutionContext(
                run_id=context.run_id,
                parent_context=context,
                depth=context.depth,
                max_depth=context.max_depth,
                bag=dict(context.bag),
                step_outputs=dict(context.step_outputs),
                step_results=dict(context.step_results),
                call_chain=list(context.call_chain),
            )
            for _ in step.branches
        ]
        tasks = [
            self._execute_step(branch, context=branch_ctx, runtime=runtime)
            for branch, branch_ctx in zip(step.branches, branch_contexts)
        ]

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        branch_results: List[CapabilityResult] = []
        for r in raw_results:
            if isinstance(r, Exception):
                branch_results.append(
                    CapabilityResult(status=CapabilityStatus.FAILED, error=str(r))
                )
            else:
                branch_results.append(r)

        if step.join_strategy == "all_success":
            non_success = [r for r in branch_results if r.status != CapabilityStatus.SUCCESS]
            if non_success:
                # 优先级：PENDING > FAILED > CANCELLED > RUNNING（避免误把 needs_approval 当成失败吞掉）
                statuses = {r.status for r in non_success}
                if CapabilityStatus.PENDING in statuses:
                    overall = CapabilityStatus.PENDING
                elif CapabilityStatus.FAILED in statuses:
                    overall = CapabilityStatus.FAILED
                elif CapabilityStatus.CANCELLED in statuses:
                    overall = CapabilityStatus.CANCELLED
                else:
                    overall = CapabilityStatus.RUNNING

                context.step_outputs[step.id] = [r.output for r in branch_results]
                aggregated = CapabilityResult(
                    status=overall,
                    output=[r.output for r in branch_results],
                    error=(
                        f"ParallelStep '{step.id}': "
                        f"{len(non_success)}/{len(branch_results)} branches not success"
                    )
                    if overall == CapabilityStatus.FAILED
                    else None,
                    metadata={
                        "branch_statuses": [
                            getattr(r.status, "value", str(r.status)) for r in branch_results
                        ]
                    },
                )
                context.step_results[step.id] = _to_step_result_dict(aggregated)
                return aggregated
        elif step.join_strategy == "any_success":
            if not any(r.status == CapabilityStatus.SUCCESS for r in branch_results):
                statuses = {r.status for r in branch_results}
                if CapabilityStatus.PENDING in statuses:
                    overall = CapabilityStatus.PENDING
                elif CapabilityStatus.CANCELLED in statuses:
                    overall = CapabilityStatus.CANCELLED
                elif CapabilityStatus.RUNNING in statuses:
                    overall = CapabilityStatus.RUNNING
                else:
                    overall = CapabilityStatus.FAILED

                context.step_outputs[step.id] = [r.output for r in branch_results]
                aggregated = CapabilityResult(
                    status=overall,
                    output=[r.output for r in branch_results],
                    error=f"ParallelStep '{step.id}': no branch succeeded"
                    if overall == CapabilityStatus.FAILED
                    else None,
                    metadata={
                        "branch_statuses": [
                            getattr(r.status, "value", str(r.status)) for r in branch_results
                        ]
                    },
                )
                context.step_results[step.id] = _to_step_result_dict(aggregated)
                return aggregated

        context.step_outputs[step.id] = [r.output for r in branch_results]
        aggregated = CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output=[r.output for r in branch_results],
        )
        context.step_results[step.id] = _to_step_result_dict(aggregated)
        return aggregated

    async def _execute_conditional_step(
        self,
        step: ConditionalStep,
        *,
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """执行条件步骤。"""
        condition_value = context.resolve_mapping(step.condition_source)
        condition_key = str(condition_value) if condition_value is not None else ""

        branch = step.branches.get(condition_key, step.default)
        if branch is None:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=(
                    f"ConditionalStep '{step.id}': no branch for "
                    f"condition '{condition_key}' and no default"
                ),
            )

        result = await self._execute_step(branch, context=context, runtime=runtime)
        context.step_outputs[step.id] = result.output
        context.step_results[step.id] = _to_step_result_dict(result)
        return result

    @staticmethod
    def _resolve_input_mappings(
        mappings: List[InputMapping],
        context: ExecutionContext,
    ) -> Dict[str, Any]:
        """解析输入映射列表。"""
        result: Dict[str, Any] = {}
        for m in mappings:
            value = context.resolve_mapping(m.source)
            result[m.target_field] = value
        return result

    @staticmethod
    def _resolve_output_mappings(
        mappings: List[InputMapping],
        context: ExecutionContext,
    ) -> Any:
        """解析输出映射列表。"""
        if not mappings:
            return None
        result: Dict[str, Any] = {}
        for m in mappings:
            value = context.resolve_mapping(m.source)
            result[m.target_field] = value
        return result
