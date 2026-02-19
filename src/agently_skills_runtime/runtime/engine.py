"""CapabilityRuntime：能力组织层主入口。"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from ..protocol.capability import CapabilityKind, CapabilityResult, CapabilityStatus
from ..protocol.context import ExecutionContext, RecursionLimitError
from .guards import ExecutionGuards, LoopBreakerError
from .loop import LoopController
from .registry import AnySpec, CapabilityRegistry, _get_base


@dataclass(frozen=True)
class RuntimeConfig:
    """
    能力运行时配置。

    参数：
    - max_depth: 最大嵌套深度
    - max_total_loop_iterations: 全局循环迭代上限
    - default_loop_max_iterations: LoopStep 默认 max_iterations
    """

    max_depth: int = 10
    max_total_loop_iterations: int = 50000
    default_loop_max_iterations: int = 200


@runtime_checkable
class AdapterProtocol(Protocol):
    """
    Adapter 执行协议。所有 Adapter 必须实现此接口。

    参数说明：
    - spec: 具体的 Spec（AgentSpec/WorkflowSpec/SkillSpec）
    - input: 输入参数字典
    - context: 执行上下文
    - runtime: CapabilityRuntime 实例（供 Adapter 回调 _execute 实现递归调度）
    """

    async def execute(
        self,
        *,
        spec: Any,
        input: Dict[str, Any],
        context: ExecutionContext,
        runtime: "CapabilityRuntime",
    ) -> CapabilityResult: ...


class CapabilityRuntime:
    """
    CapabilityRuntime：框架主入口。

    使用流程：
    1. 创建 runtime = CapabilityRuntime(config=RuntimeConfig())
    2. 注入 adapters: runtime.set_adapter(CapabilityKind.AGENT, my_agent_adapter)
    3. 注册能力: runtime.register(agent_spec)
    4. 校验依赖: missing = runtime.validate(); assert not missing
    5. 执行: result = await runtime.run("capability-id", input={...})
    """

    def __init__(self, *, config: RuntimeConfig = RuntimeConfig()):
        self.config = config
        self.registry = CapabilityRegistry()
        self._guards = ExecutionGuards(
            max_total_loop_iterations=config.max_total_loop_iterations,
        )
        self._loop_controller = LoopController(guards=self._guards)
        self._adapters: Dict[CapabilityKind, AdapterProtocol] = {}

    def set_adapter(self, kind: CapabilityKind, adapter: AdapterProtocol) -> None:
        """注入指定种类的 Adapter。"""
        self._adapters[kind] = adapter

    def register(self, spec: AnySpec) -> None:
        """注册一个能力。"""
        self.registry.register(spec)

    def register_many(self, specs: List[AnySpec]) -> None:
        """批量注册能力。"""
        for spec in specs:
            self.registry.register(spec)

    def validate(self) -> List[str]:
        """校验所有依赖，返回缺失的能力 ID 列表。"""
        return self.registry.validate_dependencies()

    async def run(
        self,
        capability_id: str,
        *,
        input: Optional[Dict[str, Any]] = None,
        context_bag: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        max_depth: Optional[int] = None,
    ) -> CapabilityResult:
        """
        执行指定能力（顶层入口）。

        参数：
        - capability_id: 能力 ID
        - input: 输入参数
        - context_bag: 初始 context bag
        - run_id: 运行 ID（不指定则自动生成）
        - max_depth: 最大嵌套深度覆盖

        返回：CapabilityResult
        """
        self._guards.reset()

        spec = self.registry.get(capability_id)
        if spec is None:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"Capability not found: {capability_id!r}",
                metadata={"error_type": "not_found"},
            )

        ctx = ExecutionContext(
            run_id=run_id or uuid.uuid4().hex,
            max_depth=max_depth or self.config.max_depth,
            bag=dict(context_bag or {}),
        )

        start_time = time.monotonic()
        result = await self._execute(spec, input=input or {}, context=ctx)
        duration_ms = (time.monotonic() - start_time) * 1000
        result.duration_ms = duration_ms
        return result

    async def _execute(
        self,
        spec: AnySpec,
        *,
        input: Dict[str, Any],
        context: ExecutionContext,
    ) -> CapabilityResult:
        """
        内部执行——创建子 context，分发到 Adapter。

        此方法被 Engine 自身和 WorkflowAdapter 递归调用。
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

        adapter = self._adapters.get(base.kind)
        if adapter is None:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"No adapter registered for kind: {base.kind.value}",
                metadata={"error_type": "no_adapter"},
            )

        try:
            return await adapter.execute(
                spec=spec,
                input=input,
                context=child_ctx,
                runtime=self,
            )
        except LoopBreakerError as exc:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=str(exc),
                metadata={"error_type": "loop_breaker"},
            )
        except Exception as exc:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"Adapter execution error: {exc}",
                metadata={
                    "error_type": "adapter_error",
                    "exception_class": type(exc).__name__,
                },
            )

    @property
    def loop_controller(self) -> LoopController:
        """供 WorkflowAdapter 使用的循环控制器。"""
        return self._loop_controller

    @property
    def guards(self) -> ExecutionGuards:
        """供 Adapter 使用的全局守卫。"""
        return self._guards

