from __future__ import annotations

"""
统一运行时：声明 → 注册 → 校验 → 执行 → 报告。

定位：
- 对外只提供一个执行入口（Runtime），避免“双入口/双路径”导致的语义分叉；
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
from .types import NodeReport
from .adapters.workflow_engine import WorkflowStreamEvent
from .adapters.triggerflow_workflow_engine import TriggerFlowWorkflowEngine
from .runtime_ui_events_mixin import RuntimeUIEventsMixin


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
        """

        self._config = config
        self._registry = CapabilityRegistry()
        self._last_node_report: Optional[NodeReport] = None
        self._sdk: Optional[SdkLifecycle] = None
        # 兼容保留：部分内部逻辑仍通过 `_sdk_state` 读取 skills_config（仅只读）。
        self._sdk_state: Any = None
        self._output_validator = OutputValidator(
            mode=self._config.output_validation_mode,
            validator=self._config.output_validator,
        )
        self._last_lock = asyncio.Lock()
        # UI events taps：用于把 SDK AgentEvent（含 workflow 内 nested agent 事件）
        # 旁路投影为 RuntimeEvent v1，不影响 NodeReport/WAL 真相源。
        self._agent_event_taps: List[Any] = []
        from .adapters.agent_adapter import AgentAdapter

        self._agent_adapter = AgentAdapter(services=self)
        injected_engine = getattr(config, "workflow_engine", None)
        self._workflow_engine = injected_engine if injected_engine is not None else TriggerFlowWorkflowEngine()

        if config.mode in ("bridge", "sdk_native"):
            self._sdk = SdkLifecycle(config)
            self._sdk_state = self._sdk.state
            # 兼容：大部分调用方仅提供 sdk_config_paths（overlay），并不显式传 skills_config。
            # 为了让 Adapter/Engine 只依赖 RuntimeServices.config（而不读取内部 _sdk_state），
            # 这里把“有效 skills_config”回填到对外暴露的 config 视图中（只读替换）。
            if self._config.skills_config is None:
                self._config = replace(self._config, skills_config=self._sdk_state.skills_config)

    @property
    def config(self) -> RuntimeConfig:
        """运行时配置（只读）。"""

        return self._config

    def register(self, spec: AnySpec) -> None:
        """
        注册一个能力。

        参数：
        - spec：AgentSpec 或 WorkflowSpec
        """

        self._registry.register(spec)

    def register_many(self, specs: List[AnySpec]) -> None:
        """批量注册能力。"""

        for s in specs:
            self._registry.register(s)

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
        - 如果你需要“单一稳定事件协议 + 续传游标 + 最小披露”，请使用 `run_ui_events()` / `start_ui_events_session()`。
        """

        spec = self._registry.get(capability_id)
        if spec is None:
            yield CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"Capability not found: {capability_id!r}",
            )
            return

        guards = ExecutionGuards(max_total_loop_iterations=self._config.max_total_loop_iterations)
        ctx = context or ExecutionContext(
            run_id=uuid.uuid4().hex,
            max_depth=self._config.max_depth,
            guards=guards,
        )
        if ctx.guards is None:
            ctx.guards = guards

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

    async def _execute(self, *, spec: AnySpec, input: Dict[str, Any], context: ExecutionContext) -> CapabilityResult:
        """
        内部执行：创建子 context 并分发到 Agent/Workflow 执行器。

        参数：
        - spec：能力声明
        - input：输入参数
        - context：执行上下文
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
            if isinstance(item, CapabilityResult) and item.node_report is not None:
                async with self._last_lock:
                    self._last_node_report = item.node_report
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
        final_output: str,
        report: NodeReport,
        context: Dict[str, Any],
    ) -> None:
        """
        RuntimeServices 协议方法：执行输出校验并写入 NodeReport.meta。
        """

        self._output_validator.validate(final_output=final_output, report=report, context=context)

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

    def create_sdk_agent(self) -> Any:
        """RuntimeServices 协议方法：创建 per-run SDK Agent。"""

        if self._sdk is None:
            raise RuntimeError("SDK lifecycle is not initialized")
        return self._sdk.create_agent(custom_tools=list(self._config.custom_tools))

    @property
    def last_node_report(self) -> Optional[NodeReport]:
        """最近一次 bridge/sdk_native 执行产出的 NodeReport（可选便利属性）。"""

        return self._last_node_report
