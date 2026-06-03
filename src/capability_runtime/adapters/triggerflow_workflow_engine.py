"""WorkflowEngine 的 TriggerFlow 实现（内部细节，不对外暴露）。"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, AsyncIterator, Dict, List, Optional, cast

from agently import TriggerFlow

from ..host_protocol import build_approval_ticket_from_report
from ..logging_utils import log_suppressed_exception
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
from ..types import NodeReport
from .workflow_engine import WorkflowStreamEvent, WorkflowStreamItem


_WF_WORKFLOW_ID_KEY = "__wf_workflow_id"
_WF_WORKFLOW_INSTANCE_ID_KEY = "__wf_workflow_instance_id"
_WF_STEP_ID_KEY = "__wf_step_id"
_WF_BRANCH_ID_KEY = "__wf_branch_id"


@dataclass
class _WorkflowContextHolder:
    """
    可变 context 容器（消除 nonlocal 语义歧义）。

    说明：
    - ExecutionContext 字段语义上应被视为不可变；
    - LoopStep.collect_as 需要更新 context.bag；
    - 通过持有可变引用来传递更新，而非使用 nonlocal 重绑定。
    """

    context: ExecutionContext


def _to_step_result_dict(result: CapabilityResult) -> Dict[str, Any]:
    """把 CapabilityResult 归一为 workflow step_results 的最小可编排结构。"""

    return {
        "status": getattr(result.status, "value", str(result.status)),
        "output": result.output,
        "error": result.error,
        "report": result.report or result.node_report,
        "node_report": result.node_report,
    }


class TriggerFlowWorkflowEngine:
    """
    基于 Agently TriggerFlow 的 Workflow 执行引擎。

    设计说明：
    - TriggerFlow 仅作为内部编排执行器；
    - Runtime 对外仍只暴露 `run()`/`run_stream()`；
    - Workflow 流式输出仅提供轻量事件字典，深审计仍依赖 WAL/events。
    """

    def _build_fail_closed_result(
        self,
        *,
        services: RuntimeServices,
        context: ExecutionContext,
        workflow_id: str,
        error: str,
        error_code: str,
        reason: str,
        completion_reason: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> CapabilityResult:
        report = services.build_fail_closed_report(
            run_id=context.run_id,
            status="failed",
            reason=reason,
            completion_reason=completion_reason,
            meta={"workflow_id": workflow_id, **(meta or {})},
        )
        return CapabilityResult(
            status=CapabilityStatus.FAILED,
            error=error,
            error_code=error_code,
            report=report,
            node_report=report,
        )

    def _wrap_workflow_terminal_result(
        self,
        *,
        result: CapabilityResult,
        spec: WorkflowSpec,
        context: ExecutionContext,
        workflow_instance_id: str,
        execution_id: str,
        lifecycle_state: str,
        state_version: int,
        close_reason: str,
    ) -> CapabilityResult:
        """为 workflow 终态生成 workflow-owned NodeReport，避免复用子 step 报告。"""

        child_report = result.node_report if isinstance(result.node_report, NodeReport) else None
        report_status = "failed"
        report_reason = "workflow_failed"
        completion_reason = "workflow_failed"
        if child_report is not None and child_report.status == "needs_approval":
            report_status = "needs_approval"
            report_reason = "approval_pending"
            completion_reason = "workflow_waiting_human"
        elif result.status == CapabilityStatus.SUCCESS:
            report_status = "success"
            report_reason = None
            completion_reason = "workflow_completed"
        elif result.status == CapabilityStatus.CANCELLED:
            report_status = "incomplete"
            report_reason = "cancelled"
            completion_reason = "workflow_cancelled"
        elif result.status in (CapabilityStatus.PENDING, CapabilityStatus.RUNNING):
            report_status = "incomplete"
            report_reason = "workflow_pending"
            completion_reason = "workflow_pending"

        child_terminal: Dict[str, Any] | None = None
        if child_report is not None:
            child_terminal = {
                "status": child_report.status,
                "reason": child_report.reason,
                "completion_reason": child_report.completion_reason,
                "run_id": child_report.run_id,
            }
            if result.error_code:
                child_terminal["error_code"] = result.error_code
            if child_report.status == "failed" and child_report.reason:
                report_reason = child_report.reason
                completion_reason = child_report.completion_reason or completion_reason

        meta: Dict[str, Any] = {
            "workflow_id": str(spec.base.id),
            "workflow_instance_id": workflow_instance_id,
            "approval_requested_at_ms": 0,
            "workflow": {
                "workflow_id": str(spec.base.id),
                "workflow_instance_id": workflow_instance_id,
                "execution_id": execution_id,
                "lifecycle_state": lifecycle_state,
                "state_version": state_version,
                "close_reason": close_reason,
            }
        }
        if child_terminal is not None:
            meta["child_terminal"] = child_terminal
            if child_report is not None:
                for key in (
                    "step_id",
                    "capability_id",
                    "exception_type",
                    "approval_requested_at_ms",
                    "waiting_human_kind",
                    "final_message",
                ):
                    value = child_report.meta.get(key)
                    if value is not None:
                        meta[key] = value

        bridge = {"name": "capability-runtime"}
        if child_report is not None:
            child_agently = child_report.bridge.get("agently")
            if isinstance(child_agently, dict):
                bridge["agently"] = dict(child_agently)

        workflow_report = NodeReport(
            status=report_status,  # type: ignore[arg-type]
            reason=report_reason,
            completion_reason=completion_reason,
            engine={"name": "capability-runtime", "component": "workflow"},
            bridge=bridge,
            run_id=context.run_id,
            turn_id=child_report.turn_id if child_report is not None else None,
            events_path=child_report.events_path if child_report is not None else None,
            usage=child_report.usage if child_report is not None else None,
            activated_skills=list(child_report.activated_skills) if child_report is not None else [],
            tool_calls=list(child_report.tool_calls) if child_report is not None else [],
            artifacts=list(child_report.artifacts) if child_report is not None else [],
            meta=meta,
        )
        return replace(result, report=workflow_report, node_report=workflow_report)

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
        report = services.build_fail_closed_report(
            run_id=context.run_id,
            status="failed",
            reason="engine_error",
            completion_reason="missing_terminal_result",
            meta={"workflow_id": spec.base.id, "source": "workflow.execute"},
        )
        return CapabilityResult(
            status=CapabilityStatus.FAILED,
            error="Workflow execution produced no result",
            error_code="ENGINE_ERROR",
            report=report,
            node_report=report,
        )

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
        - 输出轻量 workflow 事件（workflow started/finished + step started/finished）；
        - lifecycle 只作为 additive 摘要事件和字段，不替代 WAL/NodeReport 真相源；
        - 不透传上游全量 AgentEvent，避免把深审计负担带到默认流里。
        - 深审计与编排分支依据应读取 WAL/events + NodeReport（真相源），而非依赖轻量事件的 payload 细节。
        """

        workflow_instance_id = uuid.uuid4().hex
        execution_id = f"wfexec-{workflow_instance_id}"
        lifecycle_state = "open"
        state_version = 0
        context = context.with_bag_overlay(**(input or {}))
        context = context.with_bag_overlay(
            **{
                _WF_WORKFLOW_ID_KEY: str(spec.base.id),
                _WF_WORKFLOW_INSTANCE_ID_KEY: str(workflow_instance_id),
            }
        )
        # 使用 _WorkflowContextHolder 替代 nonlocal context，消除闭包状态语义歧义
        context_holder = _WorkflowContextHolder(context=context)
        event_queue: asyncio.Queue[WorkflowStreamEvent | object] = asyncio.Queue()
        terminal_holder: Dict[str, CapabilityResult] = {}
        queue_stop = object()

        async def emit(event: WorkflowStreamEvent) -> None:
            await event_queue.put(event)

        def lifecycle_payload(*, state: str, version: int, close_reason: str | None = None) -> Dict[str, Any]:
            """生成本仓中立 TriggerFlow lifecycle 摘要，不暴露上游 execution 对象。"""

            payload: Dict[str, Any] = {
                "lifecycle_state": state,
                "execution_id": execution_id,
                "state_version": version,
                "lifecycle_source": "runtime_triggerflow_adapter",
                "intervention_supported": False,
                "intervention_mode": None,
                "pending_interventions": [],
            }
            if close_reason is not None:
                payload["close_reason"] = close_reason
            return payload

        await emit(
            {
                "type": "workflow.started",
                "run_id": context.run_id,
                "workflow_id": spec.base.id,
                "workflow_instance_id": workflow_instance_id,
                **lifecycle_payload(state=lifecycle_state, version=state_version),
            }
        )
        await emit(
            {
                "type": "workflow.lifecycle.changed",
                "run_id": context.run_id,
                "workflow_id": spec.base.id,
                "workflow_instance_id": workflow_instance_id,
                **lifecycle_payload(state=lifecycle_state, version=state_version),
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
                payload_raw = getattr(data, "value", None)
                payload: Dict[str, Any] = dict(payload_raw) if isinstance(payload_raw, dict) else {}
                terminal = payload.get("__terminal_result__")
                if isinstance(terminal, CapabilityResult):
                    # 终态已确定，后续 chunk 跳过执行（保持 stop-on-non-success 语义）。
                    return payload

                step_id = getattr(bound_step, "id", f"step_{bound_index}")
                step_context = context_holder.context.with_bag_overlay(**{_WF_STEP_ID_KEY: str(step_id)})

                # 取消语义（协作式）：
                # - 当前 step 执行中取消：不强制中断，由 _execute_step 内部与下一个 step 边界决定；
                # - 下一步开始前已取消：不得发出 step.started（避免误导为"已开始执行"）。
                if step_context.cancel_token is not None and step_context.cancel_token.is_cancelled:
                    report = services.build_fail_closed_report(
                        run_id=step_context.run_id,
                        status="incomplete",
                        reason="cancelled",
                        completion_reason="run_cancelled",
                        meta={"workflow_id": spec.base.id, "step_id": step_id},
                    )
                    payload["__terminal_result__"] = CapabilityResult(
                        status=CapabilityStatus.CANCELLED,
                        error="execution cancelled",
                        error_code="RUN_CANCELLED",
                        report=report,
                        node_report=report,
                    )
                    return payload

                await emit(
                    {
                        "type": "workflow.step.started",
                        "run_id": context_holder.context.run_id,
                        "workflow_id": spec.base.id,
                        "workflow_instance_id": workflow_instance_id,
                        "step_id": step_id,
                        "capability_id": self._step_capability_id(bound_step),
                    }
                )

                result = await self._execute_step(cast(Any, bound_step), context=step_context, services=services)
                # 顶层 LoopStep.collect_as 需要把结果写回 workflow 级 bag，供后续步骤使用。
                # 使用 _WorkflowContextHolder 显式更新，而非 nonlocal 重绑定
                if isinstance(bound_step, LoopStep) and result.status == CapabilityStatus.SUCCESS and bound_step.collect_as:
                    context_holder.context = context_holder.context.with_bag_overlay(
                        **{str(bound_step.collect_as): result.output}
                    )

                approval_ticket = build_approval_ticket_from_report(result.node_report, capability_id=spec.base.id)
                await emit(
                    {
                        "type": "workflow.step.finished",
                        "run_id": context_holder.context.run_id,
                        "workflow_id": spec.base.id,
                        "workflow_instance_id": workflow_instance_id,
                        "step_id": step_id,
                        "capability_id": self._step_capability_id(bound_step),
                        "status": getattr(result.status, "value", str(result.status)),
                        "error": result.error,
                        "waiting_approval_key": approval_ticket.approval_key if approval_ticket is not None else None,
                    }
                )

                if result.status != CapabilityStatus.SUCCESS:
                    payload["__terminal_result__"] = result
                else:
                    payload["__last_success_result__"] = result
                return payload

            chain = chain.to((f"wf_step_{index}_{getattr(step, 'id', index)}", run_step))

        @flow.chunk("finalize")
        async def finalize(data: Any) -> CapabilityResult:
            nonlocal lifecycle_state, state_version
            payload_raw = getattr(data, "value", None)
            payload: Dict[str, Any] = dict(payload_raw) if isinstance(payload_raw, dict) else {}
            terminal = payload.get("__terminal_result__")

            if isinstance(terminal, CapabilityResult):
                result = terminal
            else:
                output = self._resolve_output_mappings(spec.output_mappings, context_holder.context)
                if output is None:
                    output = dict(context_holder.context.step_outputs)
                last_success = payload.get("__last_success_result__")
                if isinstance(last_success, CapabilityResult):
                    result = CapabilityResult(
                        status=CapabilityStatus.SUCCESS,
                        output=output,
                        report=last_success.report,
                        node_report=last_success.node_report,
                    )
                else:
                    result = CapabilityResult(status=CapabilityStatus.SUCCESS, output=output)

            lifecycle_state = "closed"
            state_version += 1
            close_reason = getattr(result.status, "value", str(result.status))
            result = self._wrap_workflow_terminal_result(
                result=result,
                spec=spec,
                context=context_holder.context,
                workflow_instance_id=workflow_instance_id,
                execution_id=execution_id,
                lifecycle_state=lifecycle_state,
                state_version=state_version,
                close_reason=close_reason,
            )
            terminal_holder["result"] = result
            await emit(
                {
                    "type": "workflow.lifecycle.changed",
                    "run_id": context_holder.context.run_id,
                    "workflow_id": spec.base.id,
                    "workflow_instance_id": workflow_instance_id,
                    **lifecycle_payload(state=lifecycle_state, version=state_version, close_reason=close_reason),
                }
            )
            await emit(
                {
                    "type": "workflow.finished",
                    "run_id": context_holder.context.run_id,
                    "workflow_id": spec.base.id,
                    "workflow_instance_id": workflow_instance_id,
                    "status": getattr(result.status, "value", str(result.status)),
                    **lifecycle_payload(state=lifecycle_state, version=state_version, close_reason=close_reason),
                }
            )
            return result

        chain.to(finalize).end()

        async def run_flow() -> None:
            nonlocal lifecycle_state, state_version
            try:
                result = await flow.async_start(
                    {"__terminal_result__": None},
                    wait_for_result=True,
                    timeout=None,
                )
                if isinstance(result, CapabilityResult):
                    terminal_holder.setdefault("result", result)
            except Exception as exc:
                log_suppressed_exception(
                    context="workflow_triggerflow_engine",
                    exc=exc,
                    run_id=context_holder.context.run_id,
                    capability_id=spec.base.id,
                    extra={"workflow_instance_id": workflow_instance_id},
                )
                report = services.build_fail_closed_report(
                    run_id=context_holder.context.run_id,
                    status="failed",
                    reason="engine_error",
                    completion_reason="engine_exception",
                    meta={"engine_exception": type(exc).__name__, "workflow_instance_id": workflow_instance_id},
                )
                terminal_holder["result"] = CapabilityResult(
                    status=CapabilityStatus.FAILED,
                    error=f"Workflow TriggerFlow engine error: {exc}",
                    error_code="ENGINE_ERROR",
                    report=report,
                    node_report=report,
                )
                lifecycle_state = "closed"
                state_version += 1
                await emit(
                    {
                        "type": "workflow.lifecycle.changed",
                        "run_id": context_holder.context.run_id,
                        "workflow_id": spec.base.id,
                        "workflow_instance_id": workflow_instance_id,
                        **lifecycle_payload(
                            state=lifecycle_state,
                            version=state_version,
                            close_reason="engine_error",
                        ),
                    }
                )
                await emit(
                    {
                        "type": "workflow.finished",
                        "run_id": context_holder.context.run_id,
                        "workflow_id": spec.base.id,
                        "workflow_instance_id": workflow_instance_id,
                        "status": "failed",
                        **lifecycle_payload(
                            state=lifecycle_state,
                            version=state_version,
                            close_reason="engine_error",
                        ),
                    }
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
            report = services.build_fail_closed_report(
                run_id=context_holder.context.run_id,
                status="failed",
                reason="engine_error",
                completion_reason="missing_terminal_result",
                meta={"workflow_id": spec.base.id, "workflow_instance_id": workflow_instance_id},
            )
            terminal = CapabilityResult(
                status=CapabilityStatus.FAILED,
                error="Workflow execution produced no result",
                error_code="ENGINE_ERROR",
                report=report,
                node_report=report,
            )
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
            report = services.build_fail_closed_report(
                run_id=context.run_id,
                status="incomplete",
                reason="cancelled",
                completion_reason="run_cancelled",
                meta={"workflow_step": getattr(step, "id", None)},
            )
            return CapabilityResult(
                status=CapabilityStatus.CANCELLED,
                error="execution cancelled",
                error_code="RUN_CANCELLED",
                report=report,
                node_report=report,
            )

        try:
            if isinstance(step, Step):
                return await self._execute_basic_step(step, context=context, services=services)
            if isinstance(step, LoopStep):
                return await self._execute_loop_step(step, context=context, services=services)
            if isinstance(step, ParallelStep):
                return await self._execute_parallel_step(step, context=context, services=services)
            if isinstance(step, ConditionalStep):
                return await self._execute_conditional_step(step, context=context, services=services)
            return self._build_fail_closed_result(
                services=services,
                context=context,
                workflow_id="unknown",
                error=f"Unknown step type: {type(step).__name__}",
                error_code="INVALID_WORKFLOW_STEP",
                reason="invalid_workflow_step",
                completion_reason="unknown_step_type",
                meta={"actual_type": type(step).__name__},
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            step_id = getattr(step, "id", None)
            capability_id = self._step_capability_id(step)
            return self._build_fail_closed_result(
                services=services,
                context=context,
                workflow_id=str(step_id or "workflow_step"),
                error=f"workflow step exception: {type(exc).__name__}",
                error_code="WORKFLOW_STEP_EXCEPTION",
                reason="workflow_step_failed",
                completion_reason="step_exception",
                meta={
                    "step_id": step_id,
                    "capability_id": capability_id,
                    "exception_type": type(exc).__name__,
                },
            )

    def _step_capability_id(self, step: Any) -> str | None:
        """
        提取 workflow step 绑定的 capability ID。

        参数：
        - step：WorkflowStep
        """

        capability = getattr(step, "capability", None)
        capability_id = getattr(capability, "id", None)
        return capability_id if isinstance(capability_id, str) and capability_id.strip() else None

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
        execute_task: asyncio.Task[CapabilityResult] | None = None
        try:
            if step.timeout_s is not None:
                execute_task = asyncio.create_task(
                    services.execute_capability(spec=target_spec, input=step_input, context=context)
                )
                done, _pending = await asyncio.wait({execute_task}, timeout=step.timeout_s)
                if not done:
                    execute_task.cancel()
                    with suppress(BaseException):
                        await execute_task
                    raise asyncio.TimeoutError()
                result = execute_task.result()
            else:
                result = await services.execute_capability(spec=target_spec, input=step_input, context=context)
        except asyncio.TimeoutError:
            report = services.build_fail_closed_report(
                run_id=context.run_id,
                status="failed",
                reason="timeout",
                completion_reason="step_timeout",
                meta={"step_id": step.id, "capability_id": step.capability.id},
            )
            result = CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"step timeout: {step.id}",
                error_code="STEP_TIMEOUT",
                report=report,
                node_report=report,
            )
        except asyncio.CancelledError:
            if execute_task is not None:
                execute_task.cancel()
                with suppress(BaseException):
                    await execute_task
            report = services.build_fail_closed_report(
                run_id=context.run_id,
                status="incomplete",
                reason="cancelled",
                completion_reason="run_cancelled",
                meta={"step_id": step.id, "capability_id": step.capability.id},
            )
            result = CapabilityResult(
                status=CapabilityStatus.CANCELLED,
                error="execution cancelled",
                error_code="RUN_CANCELLED",
                report=report,
                node_report=report,
            )

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
            return self._build_fail_closed_result(
                services=services,
                context=context,
                workflow_id=step.id,
                error=(
                    f"LoopStep '{step.id}': iterate_over resolved to "
                    f"{type(items).__name__}, expected list"
                ),
                error_code="INVALID_LOOP_INPUT",
                reason="invalid_workflow_step",
                completion_reason="loop_iterate_over_not_list",
                meta={"step_id": step.id, "actual_type": type(items).__name__},
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
            return self._build_fail_closed_result(
                services=services,
                context=context,
                workflow_id=step.id,
                error=f"LoopStep '{step.id}': missing ExecutionGuards in ExecutionContext",
                error_code="MISSING_EXECUTION_GUARDS",
                reason="engine_error",
                completion_reason="missing_execution_guards",
                meta={"step_id": step.id},
            )

        if step.timeout_s is not None:
            loop_task: asyncio.Task[CapabilityResult] | None = None
            try:
                loop_task = asyncio.create_task(
                    context.guards.run_loop(
                        items=items,
                        max_iterations=step.max_iterations,
                        execute_fn=execute_item,
                        fail_strategy=step.fail_strategy,
                    )
                )
                done, _pending = await asyncio.wait({loop_task}, timeout=step.timeout_s)
                if not done:
                    loop_task.cancel()
                    with suppress(BaseException):
                        await loop_task
                    raise asyncio.TimeoutError()
                result = loop_task.result()
            except asyncio.TimeoutError:
                report = services.build_fail_closed_report(
                    run_id=context.run_id,
                    status="failed",
                    reason="timeout",
                    completion_reason="loop_timeout",
                    meta={"step_id": step.id, "capability_id": step.capability.id},
                )
                result = CapabilityResult(
                    status=CapabilityStatus.FAILED,
                    error=f"loop timeout: {step.id}",
                    error_code="LOOP_TIMEOUT",
                    output=[],
                    report=report,
                    node_report=report,
                )
        else:
            result = await context.guards.run_loop(
                items=items,
                max_iterations=step.max_iterations,
                execute_fn=execute_item,
                fail_strategy=step.fail_strategy,
            )

        if result.status == CapabilityStatus.FAILED and result.node_report is None:
            report = services.build_fail_closed_report(
                run_id=context.run_id,
                status="failed",
                reason="workflow_step_failed",
                completion_reason="loop_iteration_failed",
                meta={"step_id": step.id, "capability_id": step.capability.id},
            )
            result = replace(result, report=report, node_report=report)

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
            return self._build_fail_closed_result(
                services=services,
                context=context,
                workflow_id=step.id,
                error=(
                    f"ParallelStep '{step.id}': 深度 {new_depth} 超过最大值 {context.max_depth}"
                ),
                error_code="RECURSION_LIMIT",
                reason="recursion_limit",
                completion_reason="recursion_limit",
                meta={"error_type": "recursion_limit", "step_id": step.id},
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
                if isinstance(result, asyncio.CancelledError):
                    report = services.build_fail_closed_report(
                        run_id=context.run_id,
                        status="incomplete",
                        reason="cancelled",
                        completion_reason="parallel_branch_cancelled",
                        meta={"step_id": step.id, "exception_type": type(result).__name__},
                    )
                    branch_results.append(
                        CapabilityResult(
                            status=CapabilityStatus.CANCELLED,
                            error="execution cancelled",
                            error_code="RUN_CANCELLED",
                            report=report,
                            node_report=report,
                        )
                    )
                    continue
                msg = str(result).strip()
                branch_results.append(
                    self._build_fail_closed_result(
                        services=services,
                        context=context,
                        workflow_id=step.id,
                        error=msg or type(result).__name__,
                        error_code="BRANCH_EXECUTION_ERROR",
                        reason="engine_error",
                        completion_reason="parallel_branch_exception",
                        meta={"step_id": step.id, "exception_type": type(result).__name__},
                    )
                )
            else:
                branch_results.append(result)

        if step.join_strategy == "all_success":
            non_success = [result for result in branch_results if result.status != CapabilityStatus.SUCCESS]
            if non_success:
                statuses = {result.status for result in non_success}
                if CapabilityStatus.FAILED in statuses:
                    overall = CapabilityStatus.FAILED
                elif CapabilityStatus.CANCELLED in statuses:
                    overall = CapabilityStatus.CANCELLED
                elif CapabilityStatus.PENDING in statuses:
                    overall = CapabilityStatus.PENDING
                else:
                    overall = CapabilityStatus.RUNNING

                context.step_outputs[step.id] = [result.output for result in branch_results]
                branch_statuses = [
                    getattr(result.status, "value", str(result.status)) for result in branch_results
                ]
                aggregated = CapabilityResult(
                    status=overall,
                    output=[result.output for result in branch_results],
                    error=(
                        f"ParallelStep '{step.id}': "
                        f"{len(non_success)}/{len(branch_results)} branches not success"
                    )
                    if overall == CapabilityStatus.FAILED
                    else None,
                    error_code=(
                        "BRANCH_EXECUTION_ERROR"
                        if overall == CapabilityStatus.FAILED
                        and any(result.error_code == "BRANCH_EXECUTION_ERROR" for result in branch_results)
                        else ("RUN_CANCELLED" if overall == CapabilityStatus.CANCELLED else None)
                    ),
                    metadata={"branch_statuses": branch_statuses},
                )
                if overall != CapabilityStatus.SUCCESS:
                    report_status = "failed"
                    report_reason = "workflow_step_failed"
                    if overall == CapabilityStatus.CANCELLED:
                        report_status = "incomplete"
                        report_reason = "cancelled"
                    elif overall in (CapabilityStatus.PENDING, CapabilityStatus.RUNNING):
                        report_status = "incomplete"
                        report_reason = "parallel_branches_incomplete"
                    report = services.build_fail_closed_report(
                        run_id=context.run_id,
                        status=report_status,
                        reason=report_reason,
                        completion_reason="parallel_all_success_not_met",
                        meta={
                            "step_id": step.id,
                            "branch_statuses": branch_statuses,
                        },
                    )
                    aggregated.report = report
                    aggregated.node_report = report
                context.step_results[step.id] = _to_step_result_dict(aggregated)
                return aggregated
        elif step.join_strategy == "any_success":
            if not any(result.status == CapabilityStatus.SUCCESS for result in branch_results):
                statuses = {result.status for result in branch_results}
                if CapabilityStatus.FAILED in statuses:
                    overall = CapabilityStatus.FAILED
                elif CapabilityStatus.CANCELLED in statuses:
                    overall = CapabilityStatus.CANCELLED
                elif CapabilityStatus.PENDING in statuses:
                    overall = CapabilityStatus.PENDING
                elif CapabilityStatus.RUNNING in statuses:
                    overall = CapabilityStatus.RUNNING
                else:
                    overall = CapabilityStatus.FAILED

                context.step_outputs[step.id] = [result.output for result in branch_results]
                branch_statuses = [
                    getattr(result.status, "value", str(result.status)) for result in branch_results
                ]
                aggregated = CapabilityResult(
                    status=overall,
                    output=[result.output for result in branch_results],
                    error=f"ParallelStep '{step.id}': no branch succeeded"
                    if overall == CapabilityStatus.FAILED
                    else None,
                    error_code=(
                        "BRANCH_EXECUTION_ERROR"
                        if overall == CapabilityStatus.FAILED
                        and any(result.error_code == "BRANCH_EXECUTION_ERROR" for result in branch_results)
                        else ("RUN_CANCELLED" if overall == CapabilityStatus.CANCELLED else None)
                    ),
                    metadata={"branch_statuses": branch_statuses},
                )
                if overall != CapabilityStatus.SUCCESS:
                    report_status = "failed"
                    report_reason = "workflow_step_failed"
                    if overall == CapabilityStatus.CANCELLED:
                        report_status = "incomplete"
                        report_reason = "cancelled"
                    elif overall in (CapabilityStatus.PENDING, CapabilityStatus.RUNNING):
                        report_status = "incomplete"
                        report_reason = "parallel_branches_incomplete"
                    report = services.build_fail_closed_report(
                        run_id=context.run_id,
                        status=report_status,
                        reason=report_reason,
                        completion_reason="parallel_any_success_not_met",
                        meta={
                            "step_id": step.id,
                            "branch_statuses": branch_statuses,
                        },
                    )
                    aggregated.report = report
                    aggregated.node_report = report
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
            return self._build_fail_closed_result(
                services=services,
                context=context,
                workflow_id=step.id,
                error=(
                    f"ConditionalStep '{step.id}': no branch for "
                    f"condition '{condition_key}' and no default"
                ),
                error_code="CONDITIONAL_BRANCH_NOT_FOUND",
                reason="invalid_workflow_step",
                completion_reason="conditional_branch_not_found",
                meta={"step_id": step.id, "condition_key": condition_key},
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
