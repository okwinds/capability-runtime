from __future__ import annotations

"""
统一运行时：声明 → 注册 → 校验 → 执行 → 报告。

定位：
- 对外只提供一个执行入口（Runtime），避免"双入口/双路径"导致的语义分叉；
- mock/bridge/sdk_native 通过 `RuntimeConfig.mode` 切换；
- 控制面证据链以 `NodeReport` 为主（事件聚合），数据面输出保持生态兼容。
"""

import asyncio
import time
import uuid
from dataclasses import replace
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from skills_runtime.core.contracts import AgentEvent

from .config import RuntimeConfig
from .guards import ExecutionGuards
from .host_protocol import (
    ApprovalTicket,
    HostRunSnapshot,
    ResumeIntent,
    build_approval_ticket_from_report,
    build_resume_intent as build_host_resume_intent,
    summarize_host_run_result,
)
from .manifest import CapabilityDescriptor, CapabilityManifestEntry, CapabilityVisibility, build_manifest_entry_from_spec
from .output_validator import OutputValidator
from .protocol.agent import AgentSpec
from .protocol.capability import CapabilityKind, CapabilityResult, CapabilityStatus
from .protocol.context import ExecutionContext, RecursionLimitError
from .protocol.workflow import WorkflowSpec
from .registry import AnySpec, CapabilityRegistry, _get_base
from .reporting.node_report import build_fail_closed_report
from .sdk_lifecycle import (
    SdkLifecycle,
    _normalize_skills_config_for_skills_runtime,
)
from .services import call_callback, get_host_meta, redact_issue
from .structured_output import (
    finalize_structured_result,
    parse_json_object_snapshot,
    validate_structured_output,
)
from .structured_stream import StructuredStreamEvent, diff_top_level_fields
from .types import NodeReport
from .adapters.agent_adapter import AgentAdapter
from .adapters.workflow_engine import WorkflowStreamEvent
from .adapters.triggerflow_workflow_engine import TriggerFlowWorkflowEngine
from .runtime_ui_events_mixin import RuntimeUIEventsMixin
from .workflow_runtime import (
    WorkflowReplayRequest,
    WorkflowRunSnapshot,
    summarize_workflow_items,
)


class Runtime(RuntimeUIEventsMixin):
    """
    统一运行时（唯一入口）。

    关键语义：
    - 注册与校验由 Registry 驱动；
    - 执行入口只有 `run()` / `run_stream()`；
    - `run()` 基于 `run_stream()` 实现；
    - 并发安全：per-run guards、per-run SDK Agent（由实现保证不共享可变状态）。
    """

    def __init__(self, config: RuntimeConfig) -> None:
        """
        构造 Runtime。

        参数：
        - config：运行时配置（含 mode 与桥接注入点）

        注意：
        - RuntimeConfig 为 frozen dataclass；内部可能通过 `replace()` 回填有效配置；
        - 通过 `Runtime.config` 读取的配置可能与初始化时传入的实例不同。
        """

        self._config = config
        self._registry = CapabilityRegistry()
        self._sdk: Optional[SdkLifecycle] = None
        # 兼容保留：部分内部逻辑仍通过 `_sdk_state` 读取 skills_config（仅只读）。
        self._sdk_state: Any = None
        self._output_validator = OutputValidator(
            mode=self._config.output_validation_mode,
            validator=self._config.output_validator,
        )
        # UI events taps：用于把 SDK AgentEvent（含 workflow 内 nested agent 事件）
        # 旁路投影为 RuntimeEvent v1，不影响 NodeReport/WAL 真相源。
        self._agent_event_taps: List[Any] = []
        self._agent_adapter = AgentAdapter(services=self)
        injected_engine = getattr(config, "workflow_engine", None)
        self._workflow_engine = injected_engine if injected_engine is not None else TriggerFlowWorkflowEngine()

        if config.mode in ("bridge", "sdk_native"):
            self._sdk = SdkLifecycle(config)
            self._sdk_state = self._sdk.state
            # 兼容：大部分调用方仅提供 sdk_config_paths（overlay），并不显式传 skills_config。
            # 为了让 Adapter/Engine 只依赖 RuntimeServices.config（而不读取内部 _sdk_state），
            # 这里把"有效 skills_config"回填到对外暴露的 config 视图中（只读替换）。
            if self._config.skills_config is None:
                self._config = replace(self._config, skills_config=self._sdk_state.skills_config)

    @property
    def config(self) -> RuntimeConfig:
        """
        运行时配置（只读）。

        注意：
        - 返回的是运行时有效配置，可能与初始化时传入的 RuntimeConfig 实例不同；
        - 内部可能通过 `replace()` 回填 skills_config 等字段。
        """

        return self._config

    def register(self, spec: AnySpec) -> None:
        """
        注册一个能力。

        参数：
        - spec：AgentSpec 或 WorkflowSpec
        """

        self._registry.register_with_manifest(
            spec,
            entry=build_manifest_entry_from_spec(spec, source="runtime.register"),
        )

    def register_many(self, specs: List[AnySpec]) -> None:
        """批量注册能力。"""

        for s in specs:
            self._registry.register_with_manifest(
                s,
                entry=build_manifest_entry_from_spec(s, source="runtime.register_many"),
            )

    def register_manifest_entry(self, entry: CapabilityManifestEntry) -> CapabilityManifestEntry:
        """
        仅注册 manifest entry（允许先于 spec）。

        参数：
        - entry：宿主定义的 manifest 元数据

        返回：
        - 已注册的 manifest entry
        """

        return self._registry.register_manifest_entry(entry)

    def register_with_manifest(
        self,
        spec: AnySpec,
        *,
        entry: CapabilityManifestEntry | None = None,
    ) -> CapabilityManifestEntry:
        """
        注册能力并同步 manifest entry。

        参数：
        - spec：AgentSpec 或 WorkflowSpec
        - entry：可选显式 manifest entry

        返回：
        - 实际注册的 manifest entry
        """

        manifest_entry = entry or build_manifest_entry_from_spec(spec, source="runtime.register_with_manifest")
        return self._registry.register_with_manifest(spec, entry=manifest_entry)

    @property
    def registry(self) -> CapabilityRegistry:
        """
        能力注册表（只读视角）。

        说明：
        - 主要用于 workflow 引擎递归分发执行时查询 target spec；
        - 调用方不应直接修改内部状态（注册应通过 Runtime.register* 完成）。
        """

        return self._registry

    def validate(self) -> List[str]:
        """
        校验所有依赖，返回缺失能力 ID 列表。

        返回：
        - 缺失 ID 列表；空列表表示全部满足
        """

        return self._registry.validate_dependencies()

    def describe_capability(self, capability_id: str) -> CapabilityDescriptor | None:
        """
        返回宿主可消费的 capability descriptor。

        参数：
        - capability_id：能力 ID
        """

        return self._registry.get_descriptor(capability_id)

    def list_capabilities(
        self,
        *,
        visibility: CapabilityVisibility | None = None,
        exposed_only: bool = False,
    ) -> list[CapabilityDescriptor]:
        """
        列出 capability descriptors。

        参数：
        - visibility：可选可见性过滤
        - exposed_only：仅返回 `entry.expose=True` 的能力
        """

        return self._registry.list_descriptors(visibility=visibility, exposed_only=exposed_only)

    def build_approval_ticket(
        self,
        result: CapabilityResult,
        *,
        capability_id: str,
    ) -> ApprovalTicket | None:
        """
        从 terminal result 构造宿主 ApprovalTicket。

        参数：
        - result：终态 CapabilityResult
        - capability_id：能力 ID
        """

        return build_approval_ticket_from_report(result.node_report, capability_id=capability_id)

    def summarize_host_run(
        self,
        result: CapabilityResult,
        *,
        capability_id: str,
    ) -> HostRunSnapshot:
        """
        把 terminal result 收敛为宿主运行摘要。

        参数：
        - result：终态 CapabilityResult
        - capability_id：能力 ID
        """

        return summarize_host_run_result(result, capability_id=capability_id)

    def build_resume_intent(
        self,
        *,
        run_id: str,
        approval_key: str | None = None,
        decision: str | None = None,
        session_id: str | None = None,
        host_turn_id: str | None = None,
    ) -> ResumeIntent:
        """
        构造宿主续跑意图。

        参数：
        - run_id：运行 ID
        - approval_key：可选审批键
        - decision：可选审批决定
        - session_id：可选会话 ID
        - host_turn_id：可选宿主 turn ID
        """

        return build_host_resume_intent(
            run_id=run_id,
            approval_key=approval_key,
            decision=decision,
            session_id=session_id,
            host_turn_id=host_turn_id,
        )

    async def run(
        self,
        capability_id: str,
        *,
        input: Optional[Dict[str, Any]] = None,
        context: Optional[ExecutionContext] = None,
    ) -> CapabilityResult:
        """
        非流式执行（等待完成后返回）。

        参数：
        - capability_id：能力 ID
        - input：输入参数 dict
        - context：可选执行上下文（宿主控制；若不传则由 Runtime 创建）
        """

        result: Optional[CapabilityResult] = None
        async for item in self.run_stream(capability_id, input=input, context=context):
            if isinstance(item, CapabilityResult):
                result = item
        if result is None:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error="Runtime.run_stream produced no terminal CapabilityResult",
            )
        return result

    async def run_structured(
        self,
        capability_id: str,
        *,
        input: Optional[Dict[str, Any]] = None,
        context: Optional[ExecutionContext] = None,
    ) -> CapabilityResult:
        """
        强结构输出入口：成功时返回 `dict` 输出。

        约束：
        - 仅支持带 `output_schema` 的 Agent capability；
        - 不改变 `run()` 的既有语义，而是在其之上做强结构收口。
        """

        spec = self._registry.get(capability_id)
        if spec is None:
            return await self.run(capability_id, input=input, context=context)
        if not isinstance(spec, AgentSpec):
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"Structured output is only supported for Agent capability: {capability_id!r}",
                error_code="STRUCTURED_OUTPUT_UNSUPPORTED_KIND",
            )
        if spec.output_schema is None or not spec.output_schema.fields:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"Structured output schema is missing for capability: {capability_id!r}",
                error_code="STRUCTURED_OUTPUT_SCHEMA_MISSING",
            )

        result = await self.run(capability_id, input=input, context=context)
        if result.status != CapabilityStatus.SUCCESS:
            return result

        validation = validate_structured_output(
            final_output=result.output,
            output_schema=spec.output_schema,
            capability_id=capability_id,
            mode="error",
        )
        return finalize_structured_result(result=result, validation=validation, fail_on_error=True)

    async def run_structured_stream(
        self,
        capability_id: str,
        *,
        input: Optional[Dict[str, Any]] = None,
        context: Optional[ExecutionContext] = None,
    ) -> AsyncIterator[StructuredStreamEvent]:
        """
        结构化输出流式消费入口。

        说明：
        - 面向业务代码，不透传 mixed stream / UI events 的全部细节；
        - 仅在观察到 `llm_response_delta(text)` 时产出中途快照与字段更新。
        """

        spec = self._registry.get(capability_id)
        ctx = context or ExecutionContext(run_id=uuid.uuid4().hex, max_depth=self._config.max_depth)
        yield StructuredStreamEvent(type="started", run_id=ctx.run_id, capability_id=capability_id)

        if spec is None:
            yield StructuredStreamEvent(
                type="terminal",
                run_id=ctx.run_id,
                capability_id=capability_id,
                status=CapabilityStatus.FAILED.value,
                error=f"Capability not found: {capability_id!r}",
                error_code="CAPABILITY_NOT_FOUND",
            )
            return
        if not isinstance(spec, AgentSpec):
            yield StructuredStreamEvent(
                type="terminal",
                run_id=ctx.run_id,
                capability_id=capability_id,
                status=CapabilityStatus.FAILED.value,
                error=f"Structured output is only supported for Agent capability: {capability_id!r}",
                error_code="STRUCTURED_OUTPUT_UNSUPPORTED_KIND",
            )
            return
        if spec.output_schema is None or not spec.output_schema.fields:
            yield StructuredStreamEvent(
                type="terminal",
                run_id=ctx.run_id,
                capability_id=capability_id,
                status=CapabilityStatus.FAILED.value,
                error=f"Structured output schema is missing for capability: {capability_id!r}",
                error_code="STRUCTURED_OUTPUT_SCHEMA_MISSING",
            )
            return

        accumulated_text = ""
        previous_snapshot: Optional[Dict[str, Any]] = None
        terminal: Optional[CapabilityResult] = None

        async for item in self.run_stream(capability_id, input=input, context=ctx):
            if isinstance(item, CapabilityResult):
                terminal = item
                continue
            if not isinstance(item, AgentEvent):
                continue
            if item.type != "llm_response_delta":
                continue
            if str(item.payload.get("delta_type") or "") != "text":
                continue

            text = str(item.payload.get("text") or "")
            if not text:
                continue
            accumulated_text += text
            yield StructuredStreamEvent(
                type="text_delta",
                run_id=ctx.run_id,
                capability_id=capability_id,
                text=text,
            )

            snapshot = parse_json_object_snapshot(accumulated_text)
            if snapshot is None or snapshot == previous_snapshot:
                continue

            yield StructuredStreamEvent(
                type="object_snapshot",
                run_id=ctx.run_id,
                capability_id=capability_id,
                snapshot=dict(snapshot),
            )
            for field, value in diff_top_level_fields(previous_snapshot, snapshot):
                yield StructuredStreamEvent(
                    type="field_updated",
                    run_id=ctx.run_id,
                    capability_id=capability_id,
                    field=field,
                    value=value,
                )
            previous_snapshot = dict(snapshot)

        if terminal is None:
            terminal = CapabilityResult(
                status=CapabilityStatus.FAILED,
                error="Runtime.run_stream produced no terminal CapabilityResult",
                error_code="STRUCTURED_OUTPUT_MISSING_TERMINAL",
            )

        structured_terminal = terminal
        if terminal.status == CapabilityStatus.SUCCESS:
            validation = validate_structured_output(
                final_output=terminal.output,
                output_schema=spec.output_schema,
                capability_id=capability_id,
                mode="error",
            )
            structured_terminal = finalize_structured_result(
                result=terminal,
                validation=validation,
                fail_on_error=True,
            )

        raw_output = structured_terminal.metadata.get("raw_output")
        if not isinstance(raw_output, str):
            if isinstance(terminal.output, str):
                raw_output = terminal.output
            else:
                raw_output = None

        yield StructuredStreamEvent(
            type="terminal",
            run_id=ctx.run_id,
            capability_id=capability_id,
            status=structured_terminal.status.value,
            output=structured_terminal.output if isinstance(structured_terminal.output, dict) else None,
            raw_output=raw_output,
            error=structured_terminal.error,
            error_code=structured_terminal.error_code,
        )

    async def run_stream(
        self,
        capability_id: str,
        *,
        input: Optional[Dict[str, Any]] = None,
        context: Optional[ExecutionContext] = None,
    ) -> AsyncIterator[Union[AgentEvent, WorkflowStreamEvent, CapabilityResult]]:
        """
        流式执行（执行层混合流）：过程中可能产出事件，最后产出终态 CapabilityResult。

        事实定义（本方法可能产出三类 item；消费端需自行分流处理）：
        - `AgentEvent`：仅在执行 Agent 且为 bridge/sdk_native 时出现；来自上游 `skills_runtime` 的事实事件流。
        - `dict`（workflow.* 轻量事件）：仅在执行 Workflow 时出现；只表达编排进度（started/step.* /finished），不承诺深审计细节。
        - `CapabilityResult`：终态结果（最后一条）。其中 `node_report/events_path` 为证据指针（真相源仍为 WAL/events + NodeReport）。

        约束：
        - mock 模式可能只产出终态 `CapabilityResult`（无中间事件）；
        - bridge/sdk_native 模式 MUST 转发上游 `AgentEvent`（如执行路径确实进入上游引擎）；
        - 如果你需要"单一稳定事件协议 + 续传游标 + 最小披露"，请使用 `run_ui_events()` / `start_ui_events_session()`。

        注意：
        - 本方法为内部/进阶接口；消费方需自行 isinstance 分流三种类型；
        - 推荐使用 `run_ui_events()` 或 `start_ui_events_session()` 获得统一事件协议。
        """

        spec = self._registry.get(capability_id)
        if spec is None:
            yield CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"Capability not found: {capability_id!r}",
                error_code="CAPABILITY_NOT_FOUND",
            )
            return

        guards = ExecutionGuards(max_total_loop_iterations=self._config.max_total_loop_iterations)
        if context is not None:
            # 使用 with_guards() 确保 per-run 隔离，复制可变容器避免共享引用
            ctx = context.with_guards(guards)
        else:
            ctx = ExecutionContext(
                run_id=uuid.uuid4().hex,
                max_depth=self._config.max_depth,
                guards=guards,
            )

        started = time.monotonic()
        if _get_base(spec).kind == CapabilityKind.AGENT:
            async for x in self._execute_agent_stream(spec=spec, input=input or {}, context=ctx):
                if isinstance(x, CapabilityResult):
                    x.duration_ms = (time.monotonic() - started) * 1000
                yield x
            return

        async for x in self._execute_workflow_stream(spec=spec, input=input or {}, context=ctx):
            if isinstance(x, CapabilityResult):
                x.duration_ms = (time.monotonic() - started) * 1000
            yield x
        return

    async def run_workflow_observable(
        self,
        workflow_id: str,
        *,
        input: Optional[Dict[str, Any]] = None,
        context: Optional[ExecutionContext] = None,
    ) -> AsyncIterator[Union[WorkflowStreamEvent, CapabilityResult]]:
        """
        workflow host-facing observable surface。

        参数：
        - workflow_id：workflow ID
        - input：可选输入
        - context：可选执行上下文
        """

        async for item in self.run_stream(workflow_id, input=input, context=context):
            if isinstance(item, AgentEvent):
                continue
            yield item

    def summarize_workflow_run(
        self,
        *,
        workflow_id: str,
        items: list[Any],
        terminal: CapabilityResult | None = None,
    ) -> WorkflowRunSnapshot:
        """
        收敛 workflow 运行摘要。

        参数：
        - workflow_id：workflow ID
        - items：workflow 轻量事件列表
        - terminal：可选终态结果
        """

        return summarize_workflow_items(workflow_id=workflow_id, items=items, terminal=terminal)

    async def replay_workflow(
        self,
        request: WorkflowReplayRequest,
        *,
        context: Optional[ExecutionContext] = None,
    ) -> CapabilityResult:
        """
        基于 host request 重放 workflow。

        参数：
        - request：workflow replay 请求
        - context：可选执行上下文；为空时使用 request.run_id 新建
        """

        ctx = context or ExecutionContext(run_id=request.run_id, max_depth=self._config.max_depth)
        return await self.run(request.workflow_id, input=request.current_input or {}, context=ctx)

    async def _execute(self, *, spec: AnySpec, input: Dict[str, Any], context: ExecutionContext) -> CapabilityResult:
        """
        内部执行: 创建子 context 并分发到 Agent/Workflow 执行器。

        参数:
        - spec: 能力声明
        - input: 输入参数
        - context: 执行上下文
        """

        base = _get_base(spec)
        try:
            child_ctx = context.child(base.id)
        except RecursionLimitError as exc:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=str(exc),
                metadata={"error_type": "recursion_limit"},
            )

        if base.kind == CapabilityKind.AGENT:
            # 非流式入口内部执行时，仍走流式实现并收敛为最终结果。
            last: Optional[CapabilityResult] = None
            async for item in self._execute_agent_stream(spec=spec, input=input, context=child_ctx):
                if isinstance(item, CapabilityResult):
                    last = item
            return last or CapabilityResult(status=CapabilityStatus.FAILED, error="Agent execution produced no result")

        if not isinstance(spec, WorkflowSpec):
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"Invalid workflow spec type: {type(spec).__name__}",
            )
        return await self._workflow_engine.execute(spec=spec, input=input, context=child_ctx, services=self)

    async def execute_capability(
        self,
        *,
        spec: AnySpec,
        input: Dict[str, Any],
        context: ExecutionContext,
    ) -> CapabilityResult:
        """RuntimeServices 协议方法：执行能力并返回终态结果。"""

        return await self._execute(spec=spec, input=input, context=context)

    async def _execute_workflow_stream(
        self,
        *,
        spec: AnySpec,
        input: Dict[str, Any],
        context: ExecutionContext,
    ) -> AsyncIterator[Union[WorkflowStreamEvent, CapabilityResult]]:
        """执行 WorkflowSpec（流式）：轻量 workflow 事件 + 终态 CapabilityResult。"""

        base = _get_base(spec)
        try:
            child_ctx = context.child(base.id)
        except RecursionLimitError as exc:
            yield CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=str(exc),
                metadata={"error_type": "recursion_limit"},
            )
            return

        if not isinstance(spec, WorkflowSpec):
            yield CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"Invalid workflow spec type: {type(spec).__name__}",
            )
            return

        async for item in self._workflow_engine.execute_stream(
            spec=spec, input=input, context=child_ctx, services=self
        ):
            yield item

    async def _execute_agent_stream(
        self, *, spec: AnySpec, input: Dict[str, Any], context: ExecutionContext
    ) -> AsyncIterator[Union[AgentEvent, CapabilityResult]]:
        """
        执行 AgentSpec（流式）。

        说明：
        - mock 模式：直接调用 mock_handler，产出 CapabilityResult；
        - bridge/sdk_native：使用上游 SDK Agent 执行并转发 AgentEvent，最终聚合 NodeReport。
        """

        if not isinstance(spec, AgentSpec):
            yield CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"Invalid agent spec type: {type(spec).__name__}",
            )
            return

        async for item in self._agent_adapter.execute_stream(spec=spec, input=input, context=context):
            yield item

    def build_fail_closed_report(
        self,
        *,
        run_id: str,
        status: str,
        reason: Optional[str],
        completion_reason: str,
        meta: Dict[str, Any],
    ) -> NodeReport:
        """
        RuntimeServices 协议方法：构造 fail-closed NodeReport。
        """

        return build_fail_closed_report(
            run_id=run_id,
            status=status,
            reason=reason,
            completion_reason=completion_reason,
            meta=meta,
        )

    def apply_output_validation(
        self,
        *,
        final_output: Any,
        report: NodeReport,
        context: Dict[str, Any],
        output_schema: Optional[Any] = None,
    ) -> None:
        """
        RuntimeServices 协议方法：执行输出校验并写入 NodeReport.meta。
        """

        self._output_validator.validate(
            final_output=final_output,
            report=report,
            context=context,
            output_schema=output_schema,
        )

    def redact_issue(self, issue: Any) -> Dict[str, Any]:
        """RuntimeServices 协议方法：issue 最小披露归一。"""

        return redact_issue(issue)

    def get_host_meta(self, *, context: ExecutionContext) -> Dict[str, Any]:
        """RuntimeServices 协议方法：读取 host 保留元数据。"""

        return get_host_meta(context=context)

    def call_callback(self, cb: Any, *args: Any) -> None:
        """RuntimeServices 协议方法：兼容 callback 调用。"""

        call_callback(cb, *args)

    def preflight(self) -> list[Any]:
        """RuntimeServices 协议方法：执行 skills preflight。"""

        if self._sdk is None:
            return []
        return self._sdk.preflight()

    def create_sdk_agent(self, *, llm_config: Optional[Dict[str, Any]] = None) -> Any:
        """
        RuntimeServices 协议方法：创建 per-run SDK Agent。

        参数：
        - llm_config：可选 LLM 覆写配置（当前仅支持 `model` 字段覆写）
        """

        if self._sdk is None:
            raise RuntimeError("SDK lifecycle is not initialized")
        return self._sdk.create_agent(custom_tools=list(self._config.custom_tools), llm_config=llm_config)
