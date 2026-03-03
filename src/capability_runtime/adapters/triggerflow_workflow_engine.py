"""WorkflowEngine 的 TriggerFlow 实现（内部细节，不对外暴露）。"""
from __future__ import annotations

import asyncio
import uuid
from types import MappingProxyType
from typing import Any, AsyncIterator, Dict, List, cast

from agently import TriggerFlow

from ..protocol.capability import CapabilityResult, CapabilityStatus
from ..protocol.context import ExecutionContext, RecursionLimitError
from ..protocol.workflow import (
    ConditionalStep,
    InputMapping,
    LoopStep,
    ParallelStep,
    Step,
    WorkflowSpec,
    WorkflowStep,
)
from ..services import RuntimeServices
from .workflow_engine import WorkflowStreamEvent, WorkflowStreamItem


_WF_WORKFLOW_ID_KEY = "__wf_workflow_id"
_WF_WORKFLOW_INSTANCE_ID_KEY = "__wf_workflow_instance_id"
_WF_STEP_ID_KEY = "__wf_step_id"
_WF_BRANCH_ID_KEY = "__wf_branch_id"


def _to_step_result_dict(result: CapabilityResult) -> Dict[str, Any]:
    """把 CapabilityResult 归一为 workflow step_results 的最小可编排结构。"""

    return {
        "status": getattr(result.status, "value", str(result.status)),
        "output": result.output,
        "error": result.error,
        "report": result.report,
    }


class TriggerFlowWorkflowEngine:
    """
    基于 Agently TriggerFlow 的 Workflow 执行引擎。

    设计说明：
    - TriggerFlow 仅作为内部编排执行器；
    - Runtime 对外仍只暴露 `run()`/`run_stream()`；
    - Workflow 流式输出仅提供轻量事件字典，深审计仍依赖 WAL/events。
    """

    async def execute(
        self,
        *,
        spec: WorkflowSpec,
        input: Dict[str, Any],
        context: ExecutionContext,
        services: RuntimeServices,
    ) -> CapabilityResult:
        """执行 Workflow（非流式）。"""

        terminal: CapabilityResult | None = None
        async for item in self.execute_stream(spec=spec, input=input, context=context, services=services):
            if isinstance(item, CapabilityResult):
                terminal = item
        if terminal is not None:
            return terminal
        return CapabilityResult(status=CapabilityStatus.FAILED, error="Workflow execution produced no result")

    async def execute_stream(
        self,
        *,
        spec: WorkflowSpec,
        input: Dict[str, Any],
        context: ExecutionContext,
        services: RuntimeServices,
    ) -> AsyncIterator[WorkflowStreamItem]:
        """
        执行 Workflow（流式）。

        事件策略：
        - 仅输出轻量 workflow 事件（workflow started/finished + step started/finished）；
        - 不透传上游全量 AgentEvent，避免把深审计负担带到默认流里。
        - 深审计与编排分支依据应读取 WAL/events + NodeReport（真相源），而非依赖轻量事件的 payload 细节。
        """

        workflow_instance_id = uuid.uuid4().hex
        context = context.with_bag_overlay(**(input or {}))
        context = context.with_bag_overlay(
            **{
                _WF_WORKFLOW_ID_KEY: str(spec.base.id),
                _WF_WORKFLOW_INSTANCE_ID_KEY: str(workflow_instance_id),
            }
        )
        event_queue: asyncio.Queue[WorkflowStreamEvent | object] = asyncio.Queue()
        terminal_holder: Dict[str, CapabilityResult] = {}
        queue_stop = object()

        async def emit(event: WorkflowStreamEvent) -> None:
            await event_queue.put(event)

        await emit(
            {
                "type": "workflow.started",
                "run_id": context.run_id,
                "workflow_id": spec.base.id,
                "workflow_instance_id": workflow_instance_id,
            }
        )

        flow = TriggerFlow(name=f"runtime-workflow-{spec.base.id}-{context.run_id[:8]}")

        @flow.chunk("bootstrap")
        async def bootstrap(data: Any) -> Dict[str, Any]:
            payload = getattr(data, "value", None)
            if isinstance(payload, dict):
                return payload
            return {"__terminal_result__": None}

        chain = flow.to(bootstrap)

        for index, step in enumerate(spec.steps):

            async def run_step(
                data: Any,
                *,
                bound_step: WorkflowStep = step,
                bound_index: int = index,
            ) -> Dict[str, Any]:
                nonlocal context
                payload_raw = getattr(data, "value", None)
                payload: Dict[str, Any] = dict(payload_raw) if isinstance(payload_raw, dict) else {}
                terminal = payload.get("__terminal_result__")
                if isinstance(terminal, CapabilityResult):
                    # 终态已确定，后续 chunk 跳过执行（保持 stop-on-non-success 语义）。
                    return payload

                step_id = getattr(bound_step, "id", f"step_{bound_index}")
                step_context = context.with_bag_overlay(**{_WF_STEP_ID_KEY: str(step_id)})

                # 取消语义（协作式）：
                # - 当前 step 执行中取消：不强制中断，由 _execute_step 内部与下一个 step 边界决定；
                # - 下一步开始前已取消：不得发出 step.started（避免误导为“已开始执行”）。
                if step_context.cancel_token is not None and step_context.cancel_token.is_cancelled:
                    payload["__terminal_result__"] = CapabilityResult(
                        status=CapabilityStatus.CANCELLED,
                        error="execution cancelled",
                    )
                    return payload

                await emit(
                    {
                        "type": "workflow.step.started",
                        "run_id": context.run_id,
                        "workflow_id": spec.base.id,
                        "workflow_instance_id": workflow_instance_id,
                        "step_id": step_id,
                    }
                )

                result = await self._execute_step(cast(Any, bound_step), context=step_context, services=services)
                # 顶层 LoopStep.collect_as 需要把结果写回 workflow 级 bag，供后续步骤使用。
                if isinstance(bound_step, LoopStep) and result.status == CapabilityStatus.SUCCESS and bound_step.collect_as:
                    context = context.with_bag_overlay(**{str(bound_step.collect_as): result.output})

                await emit(
                    {
                        "type": "workflow.step.finished",
                        "run_id": context.run_id,
                        "workflow_id": spec.base.id,
                        "workflow_instance_id": workflow_instance_id,
                        "step_id": step_id,
                        "status": getattr(result.status, "value", str(result.status)),
                        "error": result.error,
                    }
                )

                if result.status != CapabilityStatus.SUCCESS:
                    payload["__terminal_result__"] = result
                return payload

            chain = chain.to((f"wf_step_{index}_{getattr(step, 'id', index)}", run_step))

        @flow.chunk("finalize")
        async def finalize(data: Any) -> CapabilityResult:
            payload_raw = getattr(data, "value", None)
            payload: Dict[str, Any] = dict(payload_raw) if isinstance(payload_raw, dict) else {}
            terminal = payload.get("__terminal_result__")

            if isinstance(terminal, CapabilityResult):
                result = terminal
            else:
                output = self._resolve_output_mappings(spec.output_mappings, context)
                if output is None:
                    output = dict(context.step_outputs)
                result = CapabilityResult(status=CapabilityStatus.SUCCESS, output=output)

            terminal_holder["result"] = result
            await emit(
                {
                    "type": "workflow.finished",
                    "run_id": context.run_id,
                    "workflow_id": spec.base.id,
                    "workflow_instance_id": workflow_instance_id,
                    "status": getattr(result.status, "value", str(result.status)),
                }
            )
            return result

        chain.to(finalize).end()

        async def run_flow() -> None:
            try:
                result = await flow.async_start(
                    {"__terminal_result__": None},
                    wait_for_result=True,
                    timeout=None,
                )
                if isinstance(result, CapabilityResult):
                    terminal_holder.setdefault("result", result)
            except Exception as exc:
                terminal_holder["result"] = CapabilityResult(
                    status=CapabilityStatus.FAILED,
                    error=f"Workflow TriggerFlow engine error: {exc}",
                )
            finally:
                await event_queue.put(queue_stop)

        flow_task = asyncio.create_task(run_flow())
        try:
            while True:
                item = await event_queue.get()
                if item is queue_stop:
                    break
                yield cast(WorkflowStreamEvent, item)
        finally:
            await flow_task

        terminal = terminal_holder.get("result")
        if terminal is None:
            terminal = CapabilityResult(status=CapabilityStatus.FAILED, error="Workflow execution produced no result")
        yield terminal

    async def _execute_step(
        self,
        step: Any,
        *,
        context: ExecutionContext,
        services: RuntimeServices,
    ) -> CapabilityResult:
        """按步骤类型分发执行。"""

        if context.cancel_token is not None and context.cancel_token.is_cancelled:
            return CapabilityResult(status=CapabilityStatus.CANCELLED, error="execution cancelled")

        if isinstance(step, Step):
            return await self._execute_basic_step(step, context=context, services=services)
        if isinstance(step, LoopStep):
            return await self._execute_loop_step(step, context=context, services=services)
        if isinstance(step, ParallelStep):
            return await self._execute_parallel_step(step, context=context, services=services)
        if isinstance(step, ConditionalStep):
            return await self._execute_conditional_step(step, context=context, services=services)
        return CapabilityResult(
            status=CapabilityStatus.FAILED,
            error=f"Unknown step type: {type(step).__name__}",
        )

    async def _execute_basic_step(
        self,
        step: Step,
        *,
        context: ExecutionContext,
        services: RuntimeServices,
    ) -> CapabilityResult:
        """执行基础步骤。"""

        step_input = self._resolve_input_mappings(step.input_mappings, context)
        target_spec = services.registry.get_or_raise(step.capability.id)
        if step.timeout_s is not None:
            try:
                result = await asyncio.wait_for(
                    services.execute_capability(spec=target_spec, input=step_input, context=context),
                    timeout=step.timeout_s,
                )
            except asyncio.TimeoutError:
                result = CapabilityResult(
                    status=CapabilityStatus.FAILED,
                    error=f"step timeout: {step.id}",
                    error_code="STEP_TIMEOUT",
                )
        else:
            result = await services.execute_capability(spec=target_spec, input=step_input, context=context)

        context.step_outputs[step.id] = result.output
        context.step_results[step.id] = _to_step_result_dict(result)
        return result

    async def _execute_loop_step(
        self,
        step: LoopStep,
        *,
        context: ExecutionContext,
        services: RuntimeServices,
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

        target_spec = services.registry.get_or_raise(step.capability.id)

        async def execute_item(item: Any, _idx: int) -> CapabilityResult:
            # 深度递增并检查是否超限
            new_depth = context.depth + 1
            if new_depth > context.max_depth:
                raise RecursionLimitError(
                    f"LoopStep '{step.id}' item[{_idx}]: 深度 {new_depth} 超过最大值 {context.max_depth}"
                )
            item_context = ExecutionContext(
                run_id=context.run_id,
                parent_context=context,
                depth=new_depth,
                max_depth=context.max_depth,
                guards=context.guards,
                cancel_token=context.cancel_token,
                bag=MappingProxyType(
                    {
                        **dict(context.bag),
                        "__current_item__": item,
                        _WF_BRANCH_ID_KEY: f"{step.id}:{_idx}",
                    }
                ),
                step_outputs=dict(context.step_outputs),
                step_results=dict(context.step_results),
                call_chain=list(context.call_chain),
            )
            step_input = self._resolve_input_mappings(step.item_input_mappings, item_context)
            if not step_input:
                step_input = item if isinstance(item, dict) else {"item": item}
            return await services.execute_capability(spec=target_spec, input=step_input, context=item_context)

        if context.guards is None:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"LoopStep '{step.id}': missing ExecutionGuards in ExecutionContext",
            )

        if step.timeout_s is not None:
            try:
                result = await asyncio.wait_for(
                    context.guards.run_loop(
                        items=items,
                        max_iterations=step.max_iterations,
                        execute_fn=execute_item,
                        fail_strategy=step.fail_strategy,
                    ),
                    timeout=step.timeout_s,
                )
            except asyncio.TimeoutError:
                result = CapabilityResult(
                    status=CapabilityStatus.FAILED,
                    error=f"loop timeout: {step.id}",
                    error_code="LOOP_TIMEOUT",
                    output=[],
                )
        else:
            result = await context.guards.run_loop(
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
        services: RuntimeServices,
    ) -> CapabilityResult:
        """执行并行步骤。"""

        # 深度递增并检查是否超限
        new_depth = context.depth + 1
        if new_depth > context.max_depth:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=(
                    f"ParallelStep '{step.id}': 深度 {new_depth} 超过最大值 {context.max_depth}"
                ),
                metadata={"error_type": "recursion_limit"},
            )

        branch_contexts = [
            ExecutionContext(
                run_id=context.run_id,
                parent_context=context,
                depth=new_depth,
                max_depth=context.max_depth,
                guards=context.guards,
                cancel_token=context.cancel_token,
                bag=MappingProxyType({**dict(context.bag), _WF_BRANCH_ID_KEY: f"{step.id}:{i}"}),
                step_outputs=dict(context.step_outputs),
                step_results=dict(context.step_results),
                call_chain=list(context.call_chain),
            )
            for i, _ in enumerate(step.branches)
        ]
        tasks = [
            self._execute_step(branch, context=branch_ctx, services=services)
            for branch, branch_ctx in zip(step.branches, branch_contexts)
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        branch_results: List[CapabilityResult] = []
        for result in raw_results:
            if isinstance(result, BaseException):
                msg = str(result).strip()
                branch_results.append(
                    CapabilityResult(
                        status=CapabilityStatus.FAILED,
                        error=msg or type(result).__name__,
                    )
                )
            else:
                branch_results.append(result)

        if step.join_strategy == "all_success":
            non_success = [result for result in branch_results if result.status != CapabilityStatus.SUCCESS]
            if non_success:
                statuses = {result.status for result in non_success}
                if CapabilityStatus.PENDING in statuses:
                    overall = CapabilityStatus.PENDING
                elif CapabilityStatus.FAILED in statuses:
                    overall = CapabilityStatus.FAILED
                elif CapabilityStatus.CANCELLED in statuses:
                    overall = CapabilityStatus.CANCELLED
                else:
                    overall = CapabilityStatus.RUNNING

                context.step_outputs[step.id] = [result.output for result in branch_results]
                aggregated = CapabilityResult(
                    status=overall,
                    output=[result.output for result in branch_results],
                    error=(
                        f"ParallelStep '{step.id}': "
                        f"{len(non_success)}/{len(branch_results)} branches not success"
                    )
                    if overall == CapabilityStatus.FAILED
                    else None,
                    metadata={
                        "branch_statuses": [
                            getattr(result.status, "value", str(result.status)) for result in branch_results
                        ]
                    },
                )
                context.step_results[step.id] = _to_step_result_dict(aggregated)
                return aggregated
        elif step.join_strategy == "any_success":
            if not any(result.status == CapabilityStatus.SUCCESS for result in branch_results):
                statuses = {result.status for result in branch_results}
                if CapabilityStatus.PENDING in statuses:
                    overall = CapabilityStatus.PENDING
                elif CapabilityStatus.CANCELLED in statuses:
                    overall = CapabilityStatus.CANCELLED
                elif CapabilityStatus.RUNNING in statuses:
                    overall = CapabilityStatus.RUNNING
                else:
                    overall = CapabilityStatus.FAILED

                context.step_outputs[step.id] = [result.output for result in branch_results]
                aggregated = CapabilityResult(
                    status=overall,
                    output=[result.output for result in branch_results],
                    error=f"ParallelStep '{step.id}': no branch succeeded"
                    if overall == CapabilityStatus.FAILED
                    else None,
                    metadata={
                        "branch_statuses": [
                            getattr(result.status, "value", str(result.status)) for result in branch_results
                        ]
                    },
                )
                context.step_results[step.id] = _to_step_result_dict(aggregated)
                return aggregated

        context.step_outputs[step.id] = [result.output for result in branch_results]
        aggregated = CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output=[result.output for result in branch_results],
        )
        context.step_results[step.id] = _to_step_result_dict(aggregated)
        return aggregated

    async def _execute_conditional_step(
        self,
        step: ConditionalStep,
        *,
        context: ExecutionContext,
        services: RuntimeServices,
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

        branch_context = context.with_bag_overlay(
            **{_WF_BRANCH_ID_KEY: f"{step.id}:{condition_key or 'default'}"}
        )
        result = await self._execute_step(branch, context=branch_context, services=services)
        context.step_outputs[step.id] = result.output
        context.step_results[step.id] = _to_step_result_dict(result)
        return result

    @staticmethod
    def _resolve_input_mappings(mappings: List[InputMapping], context: ExecutionContext) -> Dict[str, Any]:
        """解析输入映射列表。"""

        result: Dict[str, Any] = {}
        for mapping in mappings:
            result[mapping.target_field] = context.resolve_mapping(mapping.source)
        return result

    @staticmethod
    def _resolve_output_mappings(mappings: List[InputMapping], context: ExecutionContext) -> Any:
        """解析输出映射列表。"""

        if not mappings:
            return None
        result: Dict[str, Any] = {}
        for mapping in mappings:
            result[mapping.target_field] = context.resolve_mapping(mapping.source)
        return result
