"""原型验证：事件总线与带观测的适配器。"""
from __future__ import annotations

import asyncio
import datetime as dt
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from agently_skills_runtime.protocol.capability import CapabilityResult, CapabilityStatus
from agently_skills_runtime.protocol.context import ExecutionContext
from agently_skills_runtime.protocol.workflow import (
    ConditionalStep,
    InputMapping,
    LoopStep,
    ParallelStep,
    Step,
    WorkflowSpec,
)
from agently_skills_runtime.adapters.workflow_adapter import WorkflowAdapter


_SENSITIVE_KEYS = {"api_key", "authorization", "token", "secret", "password"}


def _utc_now_iso() -> str:
    """返回 UTC ISO8601 时间字符串。"""
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _truncate(value: Any, *, limit: int = 320) -> Any:
    """把任意对象转为可展示短文本，避免 SSE 事件过大。"""
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        return value if len(value) <= limit else f"{value[:limit]}..."
    text = repr(value)
    return text if len(text) <= limit else f"{text[:limit]}..."


def _sanitize_payload(value: Any) -> Any:
    """递归脱敏 payload，防止敏感信息进入事件流。"""
    if isinstance(value, dict):
        sanitized = {}
        for key, sub_value in value.items():
            key_lower = str(key).lower()
            if key_lower in _SENSITIVE_KEYS or any(part in key_lower for part in _SENSITIVE_KEYS):
                sanitized[key] = "***"
            else:
                sanitized[key] = _sanitize_payload(sub_value)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_payload(item) for item in value)
    return value


@dataclass(frozen=True)
class EventRecord:
    """SSE 事件记录结构。"""

    id: int
    event: str
    data: Dict[str, Any]


class RunEventBus:
    """按 run_id 维护事件历史与订阅队列，支持断线回放。"""

    def __init__(self, *, history_limit: int = 4000) -> None:
        """初始化事件存储与订阅索引。"""
        self._history_limit = history_limit
        self._history: Dict[str, List[EventRecord]] = {}
        self._next_id: Dict[str, int] = {}
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def ensure_run(self, run_id: str) -> None:
        """确保 run_id 在总线上已初始化。"""
        async with self._lock:
            self._history.setdefault(run_id, [])
            self._subscribers.setdefault(run_id, [])
            self._next_id.setdefault(run_id, 1)

    async def publish(self, run_id: str, event: str, data: Optional[Dict[str, Any]] = None) -> EventRecord:
        """发布事件并广播给订阅者，同时写入历史缓存。"""
        payload = dict(data or {})
        payload.setdefault("run_id", run_id)
        payload.setdefault("ts", _utc_now_iso())
        payload = _sanitize_payload(payload)

        async with self._lock:
            self._history.setdefault(run_id, [])
            self._subscribers.setdefault(run_id, [])
            self._next_id.setdefault(run_id, 1)

            event_id = self._next_id[run_id]
            self._next_id[run_id] = event_id + 1

            record = EventRecord(id=event_id, event=event, data=payload)
            run_history = self._history[run_id]
            run_history.append(record)
            if len(run_history) > self._history_limit:
                del run_history[: len(run_history) - self._history_limit]
            subscribers = list(self._subscribers[run_id])

        for queue in subscribers:
            await queue.put(record)

        return record

    async def subscribe(self, run_id: str) -> asyncio.Queue:
        """订阅指定 run_id 的实时事件。"""
        await self.ensure_run(run_id)
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._subscribers[run_id].append(queue)
        return queue

    async def unsubscribe(self, run_id: str, queue: asyncio.Queue) -> None:
        """取消 run_id 订阅。"""
        async with self._lock:
            subscribers = self._subscribers.get(run_id, [])
            if queue in subscribers:
                subscribers.remove(queue)

    def get_history(self, run_id: str, *, after_id: int = 0) -> List[Dict[str, Any]]:
        """获取事件历史（用于测试和 SSE 断线重放）。"""
        records = self._history.get(run_id, [])
        return [
            {"id": rec.id, "event": rec.event, "data": dict(rec.data)}
            for rec in records
            if rec.id > after_id
        ]


class InstrumentedAdapter:
    """包装任意 Adapter，在执行前后推送 step 事件。"""

    def __init__(self, *, inner: Any, event_bus: RunEventBus) -> None:
        """注入被包装 adapter 与事件总线。"""
        self._inner = inner
        self._event_bus = event_bus

    async def execute(
        self,
        *,
        spec: Any,
        input: Dict[str, Any],
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """执行包装 adapter，并发送 step_start/step_complete/error 事件。"""
        capability_id = spec.base.id
        await self._event_bus.publish(
            context.run_id,
            "step_start",
            {
                "step_id": capability_id,
                "capability_id": capability_id,
                "name": spec.base.name,
                "type": spec.base.kind.value,
                "input_preview": _truncate(input),
            },
        )

        start_time = time.monotonic()
        try:
            result = await self._inner.execute(
                spec=spec,
                input=input,
                context=context,
                runtime=runtime,
            )
        except Exception as exc:
            elapsed_ms = round((time.monotonic() - start_time) * 1000, 1)
            await self._event_bus.publish(
                context.run_id,
                "error",
                {
                    "step_id": capability_id,
                    "capability_id": capability_id,
                    "message": f"{type(exc).__name__}: {exc}",
                    "duration_ms": elapsed_ms,
                },
            )
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"Adapter execution error: {exc}",
            )

        elapsed_ms = round((time.monotonic() - start_time) * 1000, 1)
        await self._event_bus.publish(
            context.run_id,
            "step_complete",
            {
                "step_id": capability_id,
                "capability_id": capability_id,
                "status": result.status.value,
                "duration_ms": elapsed_ms,
                "output_preview": _truncate(result.output),
                "error": result.error,
            },
        )
        if result.status == CapabilityStatus.FAILED:
            await self._event_bus.publish(
                context.run_id,
                "error",
                {
                    "step_id": capability_id,
                    "capability_id": capability_id,
                    "message": result.error or "Unknown failure",
                },
            )
        return result


class InstrumentedWorkflowAdapter(WorkflowAdapter):
    """为 Workflow 执行补齐步骤级与流程级事件。"""

    def __init__(self, *, event_bus: RunEventBus) -> None:
        """注入事件总线。"""
        super().__init__()
        self._event_bus = event_bus

    async def execute(
        self,
        *,
        spec: WorkflowSpec,
        input: Dict[str, Any],
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """执行 Workflow，并在结束时发送 workflow_complete 或 error。"""
        start_time = time.monotonic()
        context.bag.update(input)

        for step in spec.steps:
            result = await self._execute_step(step, context=context, runtime=runtime)
            if result.status == CapabilityStatus.FAILED:
                elapsed_ms = round((time.monotonic() - start_time) * 1000, 1)
                await self._event_bus.publish(
                    context.run_id,
                    "workflow_complete",
                    {
                        "workflow_id": spec.base.id,
                        "status": CapabilityStatus.FAILED.value,
                        "duration_ms": elapsed_ms,
                        "error": result.error,
                        "output": _truncate(result.output),
                    },
                )
                return result

        output = self._resolve_output_mappings(spec.output_mappings, context)
        if output is None:
            output = dict(context.step_outputs)

        elapsed_ms = round((time.monotonic() - start_time) * 1000, 1)
        await self._event_bus.publish(
            context.run_id,
            "workflow_complete",
            {
                "workflow_id": spec.base.id,
                "status": CapabilityStatus.SUCCESS.value,
                "duration_ms": elapsed_ms,
                "output": output,
            },
        )
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=output)

    async def _execute_step(
        self,
        step: Any,
        *,
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """按 step 类型分派执行。"""
        if isinstance(step, Step):
            return await self._execute_basic_step(step, context=context, runtime=runtime)
        if isinstance(step, LoopStep):
            return await self._execute_loop_step(step, context=context, runtime=runtime)
        if isinstance(step, ParallelStep):
            return await self._execute_parallel_step(step, context=context, runtime=runtime)
        if isinstance(step, ConditionalStep):
            return await self._execute_conditional_step(step, context=context, runtime=runtime)
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
        """执行普通 Step，并推送 start/complete/error 事件。"""
        await self._event_bus.publish(
            context.run_id,
            "step_start",
            {
                "step_id": step.id,
                "capability_id": step.capability.id,
                "type": "Step",
            },
        )

        start_time = time.monotonic()
        step_input = self._resolve_input_mappings(step.input_mappings, context)
        target_spec = runtime.registry.get_or_raise(step.capability.id)
        result = await runtime._execute(target_spec, input=step_input, context=context)

        context.step_outputs[step.id] = result.output
        await self._event_bus.publish(
            context.run_id,
            "step_complete",
            {
                "step_id": step.id,
                "capability_id": step.capability.id,
                "status": result.status.value,
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
                "output_preview": _truncate(result.output),
                "error": result.error,
            },
        )
        if result.status == CapabilityStatus.FAILED:
            await self._event_bus.publish(
                context.run_id,
                "error",
                {
                    "step_id": step.id,
                    "capability_id": step.capability.id,
                    "message": result.error or "Step failed",
                },
            )
        return result

    async def _execute_loop_step(
        self,
        step: LoopStep,
        *,
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """执行 LoopStep，并在每个迭代发送 loop_item 事件。"""
        await self._event_bus.publish(
            context.run_id,
            "step_start",
            {
                "step_id": step.id,
                "capability_id": step.capability.id,
                "type": "LoopStep",
            },
        )

        start_time = time.monotonic()
        items = context.resolve_mapping(step.iterate_over)
        if not isinstance(items, list):
            result = CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=(
                    f"LoopStep '{step.id}': iterate_over resolved to "
                    f"{type(items).__name__}, expected list"
                ),
            )
            await self._event_bus.publish(
                context.run_id,
                "error",
                {
                    "step_id": step.id,
                    "capability_id": step.capability.id,
                    "message": result.error,
                },
            )
            await self._event_bus.publish(
                context.run_id,
                "step_complete",
                {
                    "step_id": step.id,
                    "capability_id": step.capability.id,
                    "status": result.status.value,
                    "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
                    "error": result.error,
                },
            )
            return result

        target_spec = runtime.registry.get_or_raise(step.capability.id)

        async def execute_item(item: Any, idx: int) -> CapabilityResult:
            """执行单个循环元素并推送 loop_item 事件。"""
            item_context = ExecutionContext(
                run_id=context.run_id,
                parent_context=context,
                depth=context.depth,
                max_depth=context.max_depth,
                bag={**context.bag, "__current_item__": item},
                step_outputs=dict(context.step_outputs),
                call_chain=list(context.call_chain),
            )
            step_input = self._resolve_input_mappings(step.item_input_mappings, item_context)
            if not step_input:
                step_input = item if isinstance(item, dict) else {"item": item}

            try:
                item_result = await runtime._execute(
                    target_spec,
                    input=step_input,
                    context=item_context,
                )
            except Exception as exc:
                item_result = CapabilityResult(
                    status=CapabilityStatus.FAILED,
                    error=f"Loop iteration {idx} exception: {exc}",
                )

            await self._event_bus.publish(
                context.run_id,
                "loop_item",
                {
                    "step_id": step.id,
                    "index": idx,
                    "item": _loop_item_label(item),
                    "status": item_result.status.value,
                    "error": item_result.error,
                },
            )
            return item_result

        result = await runtime.loop_controller.run_loop(
            items=items,
            max_iterations=step.max_iterations,
            execute_fn=execute_item,
            fail_strategy=step.fail_strategy,
        )

        context.step_outputs[step.id] = result.output
        await self._event_bus.publish(
            context.run_id,
            "step_complete",
            {
                "step_id": step.id,
                "capability_id": step.capability.id,
                "status": result.status.value,
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
                "output_preview": _truncate(result.output),
                "error": result.error,
            },
        )
        if result.status == CapabilityStatus.FAILED:
            await self._event_bus.publish(
                context.run_id,
                "error",
                {
                    "step_id": step.id,
                    "capability_id": step.capability.id,
                    "message": result.error or "Loop step failed",
                },
            )
        return result

    async def _execute_parallel_step(
        self,
        step: ParallelStep,
        *,
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """执行 ParallelStep，并发送并行分支事件。"""
        await self._event_bus.publish(
            context.run_id,
            "step_start",
            {
                "step_id": step.id,
                "capability_id": "parallel",
                "type": "ParallelStep",
            },
        )
        await self._event_bus.publish(
            context.run_id,
            "parallel_start",
            {
                "step_id": step.id,
                "branches": [branch.id for branch in step.branches],
            },
        )

        start_time = time.monotonic()
        tasks = [self._execute_step(branch, context=context, runtime=runtime) for branch in step.branches]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        branch_results: List[CapabilityResult] = []
        for branch, raw in zip(step.branches, raw_results):
            if isinstance(raw, Exception):
                result = CapabilityResult(status=CapabilityStatus.FAILED, error=str(raw))
            else:
                result = raw
            branch_results.append(result)
            await self._event_bus.publish(
                context.run_id,
                "branch_complete",
                {
                    "step_id": step.id,
                    "branch_id": branch.id,
                    "status": result.status.value,
                    "error": result.error,
                },
            )

        if step.join_strategy == "all_success":
            failed = [r for r in branch_results if r.status == CapabilityStatus.FAILED]
            if failed:
                result = CapabilityResult(
                    status=CapabilityStatus.FAILED,
                    output=[r.output for r in branch_results],
                    error=(
                        f"ParallelStep '{step.id}': "
                        f"{len(failed)}/{len(branch_results)} branches failed"
                    ),
                )
                await self._event_bus.publish(
                    context.run_id,
                    "error",
                    {
                        "step_id": step.id,
                        "message": result.error,
                    },
                )
                await self._event_bus.publish(
                    context.run_id,
                    "step_complete",
                    {
                        "step_id": step.id,
                        "capability_id": "parallel",
                        "status": result.status.value,
                        "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
                        "error": result.error,
                    },
                )
                return result

        if step.join_strategy == "any_success" and not any(
            r.status == CapabilityStatus.SUCCESS for r in branch_results
        ):
            result = CapabilityResult(
                status=CapabilityStatus.FAILED,
                output=[r.output for r in branch_results],
                error=f"ParallelStep '{step.id}': no branch succeeded",
            )
            await self._event_bus.publish(
                context.run_id,
                "error",
                {"step_id": step.id, "message": result.error},
            )
            await self._event_bus.publish(
                context.run_id,
                "step_complete",
                {
                    "step_id": step.id,
                    "capability_id": "parallel",
                    "status": result.status.value,
                    "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
                    "error": result.error,
                },
            )
            return result

        output = [r.output for r in branch_results]
        context.step_outputs[step.id] = output
        result = CapabilityResult(status=CapabilityStatus.SUCCESS, output=output)
        await self._event_bus.publish(
            context.run_id,
            "step_complete",
            {
                "step_id": step.id,
                "capability_id": "parallel",
                "status": result.status.value,
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
                "output_preview": _truncate(output),
            },
        )
        return result

    async def _execute_conditional_step(
        self,
        step: ConditionalStep,
        *,
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """执行 ConditionalStep，发布路由选择事件。"""
        await self._event_bus.publish(
            context.run_id,
            "step_start",
            {
                "step_id": step.id,
                "capability_id": "conditional",
                "type": "ConditionalStep",
            },
        )
        start_time = time.monotonic()

        condition_value = context.resolve_mapping(step.condition_source)
        condition_key = str(condition_value) if condition_value is not None else ""

        branch = step.branches.get(condition_key)
        selected_branch = condition_key
        if branch is None:
            branch = step.default
            selected_branch = "default"

        await self._event_bus.publish(
            context.run_id,
            "conditional_route",
            {
                "step_id": step.id,
                "condition_value": condition_key,
                "selected_branch": selected_branch,
            },
        )

        if branch is None:
            result = CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=(
                    f"ConditionalStep '{step.id}': no branch for "
                    f"condition '{condition_key}' and no default"
                ),
            )
            await self._event_bus.publish(
                context.run_id,
                "error",
                {
                    "step_id": step.id,
                    "message": result.error,
                },
            )
            await self._event_bus.publish(
                context.run_id,
                "step_complete",
                {
                    "step_id": step.id,
                    "capability_id": "conditional",
                    "status": result.status.value,
                    "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
                    "error": result.error,
                },
            )
            return result

        result = await self._execute_step(branch, context=context, runtime=runtime)
        context.step_outputs[step.id] = result.output
        await self._event_bus.publish(
            context.run_id,
            "step_complete",
            {
                "step_id": step.id,
                "capability_id": "conditional",
                "status": result.status.value,
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
                "output_preview": _truncate(result.output),
                "error": result.error,
            },
        )
        if result.status == CapabilityStatus.FAILED:
            await self._event_bus.publish(
                context.run_id,
                "error",
                {
                    "step_id": step.id,
                    "message": result.error or "Conditional branch failed",
                },
            )
        return result

    @staticmethod
    def _resolve_input_mappings(
        mappings: List[InputMapping],
        context: ExecutionContext,
    ) -> Dict[str, Any]:
        """解析输入映射列表。"""
        result: Dict[str, Any] = {}
        for mapping in mappings:
            result[mapping.target_field] = context.resolve_mapping(mapping.source)
        return result

    @staticmethod
    def _resolve_output_mappings(
        mappings: List[InputMapping],
        context: ExecutionContext,
    ) -> Any:
        """解析输出映射列表。"""
        if not mappings:
            return None
        resolved: Dict[str, Any] = {}
        for mapping in mappings:
            resolved[mapping.target_field] = context.resolve_mapping(mapping.source)
        return resolved


def _loop_item_label(item: Any) -> Any:
    """提取循环项的可读标签，用于日志展示。"""
    if isinstance(item, dict):
        for key in ("title", "name", "id"):
            if key in item:
                return item[key]
        return _truncate(item)
    return _truncate(item)
