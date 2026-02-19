"""
runtime/engine.py

CapabilityRuntime：框架主入口（注册 + 依赖校验 + 执行分发）。

说明：
- runtime 本身不依赖上游；上游桥接由 adapters/ 提供（可选）。
- 测试中可通过注入 fake adapters 验证分发与守卫逻辑（离线回归不要求上游可用）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Protocol

from ..protocol.agent import AgentSpec
from ..protocol.capability import CapabilityKind, CapabilityResult, CapabilityStatus
from ..protocol.context import ExecutionContext, RecursionLimitError
from ..protocol.skill import SkillSpec
from ..protocol.workflow import WorkflowSpec
from .guards import ExecutionGuards, LoopBreakerError
from .loop import LoopController
from .registry import AnySpec, CapabilityRegistry


@dataclass(frozen=True)
class RuntimeConfig:
    """
    运行时配置（与 CODEX_PROMPT 对齐的最小字段集合）。

    参数：
    - workspace_root：工作区根目录（用于相对路径解析；本阶段仅保留字段）。
    - sdk_config_paths：上游 SDK 配置路径列表（本阶段仅保留字段）。
    - agently_agent：宿主提供的 Agently agent 实例（本阶段仅保留字段）。
    - preflight_mode：error | warn | off（本阶段仅保留字段；人机交互不在框架边界内）。
    - max_loop_iterations：全局循环上限（LoopController 使用）。
    - max_depth：全局嵌套深度上限（ExecutionContext.max_depth 使用）。
    - skill_uri_allowlist：SkillSpec.source_type="uri" 的前缀 allowlist（默认空，表示禁用 uri）。
    """

    workspace_root: str = "."
    sdk_config_paths: list[str] = field(default_factory=list)
    agently_agent: Any = None
    preflight_mode: str = "error"
    max_loop_iterations: int = 200
    max_depth: int = 10
    skill_uri_allowlist: list[str] = field(default_factory=list)


class SkillAdapterLike(Protocol):
    """Skill adapter 执行协议（后续由 adapters/skill_adapter.py 实现）。"""

    async def execute(
        self, *, spec: SkillSpec, input: dict[str, Any], context: ExecutionContext, runtime: CapabilityRuntime
    ) -> CapabilityResult:
        """执行 Skill 并返回结果。"""


class AgentAdapterLike(Protocol):
    """Agent adapter 执行协议（后续由 adapters/agent_adapter.py 实现）。"""

    async def execute(
        self, *, spec: AgentSpec, input: dict[str, Any], context: ExecutionContext, runtime: CapabilityRuntime
    ) -> CapabilityResult:
        """执行 Agent 并返回结果。"""


class WorkflowAdapterLike(Protocol):
    """Workflow adapter 执行协议（后续由 adapters/workflow_adapter.py 实现）。"""

    async def execute(
        self, *, spec: WorkflowSpec, input: dict[str, Any], context: ExecutionContext, runtime: CapabilityRuntime
    ) -> CapabilityResult:
        """执行 Workflow 并返回结果。"""


class CapabilityRuntime:
    """
    CapabilityRuntime：框架主入口。

    用法：
    - runtime = CapabilityRuntime(config=RuntimeConfig(...))
    - runtime.register(spec)
    - runtime.validate()
    - result = await runtime.run(capability_id, input=..., context_bag=..., run_id=..., max_depth=...)
    """

    def __init__(
        self,
        *,
        config: RuntimeConfig,
        registry: CapabilityRegistry | None = None,
        skill_adapter: SkillAdapterLike | None = None,
        agent_adapter: AgentAdapterLike | None = None,
        workflow_adapter: WorkflowAdapterLike | None = None,
        guards: ExecutionGuards | None = None,
        loop_controller: LoopController | None = None,
    ) -> None:
        """
        创建 CapabilityRuntime。

        参数：
        - config：RuntimeConfig
        - registry：可选自定义注册表
        - skill_adapter/agent_adapter/workflow_adapter：适配器实例（本阶段测试注入 fake）
        - guards：可选自定义 ExecutionGuards
        - loop_controller：可选自定义 LoopController
        """

        self.config = config
        self.registry = registry or CapabilityRegistry()
        self.guards = guards or ExecutionGuards()
        self.loop_controller = loop_controller or LoopController(guards=self.guards)

        self._skill_adapter = skill_adapter
        self._agent_adapter = agent_adapter
        self._workflow_adapter = workflow_adapter

    def register(self, spec: AnySpec) -> None:
        """
        注册能力声明。

        参数：
        - spec：SkillSpec / AgentSpec / WorkflowSpec
        """

        self.registry.register(spec)

    def validate(self) -> None:
        """
        校验依赖（fail-fast）。

        异常：
        - ValueError：存在缺失依赖
        """

        errors = self.registry.validate_dependencies()
        if errors:
            raise ValueError("dependency validation failed:\n" + "\n".join(errors))

    async def run(
        self,
        capability_id: str,
        *,
        input: dict[str, Any] | None = None,
        context_bag: dict[str, Any] | None = None,
        run_id: str | None = None,
        max_depth: int | None = None,
    ) -> CapabilityResult:
        """
        执行指定能力（异步）。

        参数：
        - capability_id：能力 ID
        - input：输入 dict（默认空 dict）
        - context_bag：初始上下文 bag（默认空 dict）
        - run_id：可选；不提供则自动生成 UUID
        - max_depth：可选；覆盖 config.max_depth

        返回：
        - CapabilityResult
        """

        rid = run_id or str(uuid.uuid4())
        ctx = ExecutionContext(run_id=rid, depth=0, max_depth=max_depth or self.config.max_depth, bag=dict(context_bag or {}))
        return await self._execute(capability_id=capability_id, input=input or {}, context=ctx)

    async def _execute(self, *, capability_id: str, input: dict[str, Any], context: ExecutionContext) -> CapabilityResult:
        """
        执行能力的内部入口（会创建子上下文以控制递归深度）。

        参数：
        - capability_id：能力 ID
        - input：输入 dict
        - context：父 ExecutionContext

        返回：
        - CapabilityResult
        """

        try:
            child_ctx = context.child(capability_id)
        except RecursionLimitError as exc:
            return CapabilityResult(status=CapabilityStatus.FAILED, error=str(exc))

        spec = self.registry.get(capability_id)
        if spec is None:
            return CapabilityResult(status=CapabilityStatus.FAILED, error=f"capability not registered: {capability_id}")

        try:
            if spec.base.kind == CapabilityKind.SKILL:
                if self._skill_adapter is None:
                    return CapabilityResult(status=CapabilityStatus.FAILED, error="SkillAdapter is not configured")
                assert isinstance(spec, SkillSpec)
                return await self._skill_adapter.execute(spec=spec, input=input, context=child_ctx, runtime=self)

            if spec.base.kind == CapabilityKind.AGENT:
                if self._agent_adapter is None:
                    return CapabilityResult(status=CapabilityStatus.FAILED, error="AgentAdapter is not configured")
                assert isinstance(spec, AgentSpec)
                return await self._agent_adapter.execute(spec=spec, input=input, context=child_ctx, runtime=self)

            if spec.base.kind == CapabilityKind.WORKFLOW:
                if self._workflow_adapter is None:
                    return CapabilityResult(status=CapabilityStatus.FAILED, error="WorkflowAdapter is not configured")
                assert isinstance(spec, WorkflowSpec)
                return await self._workflow_adapter.execute(spec=spec, input=input, context=child_ctx, runtime=self)

            return CapabilityResult(status=CapabilityStatus.FAILED, error=f"unknown capability kind: {spec.base.kind!r}")

        except LoopBreakerError as exc:
            return CapabilityResult(status=CapabilityStatus.FAILED, error=str(exc))
        except Exception as exc:
            return CapabilityResult(status=CapabilityStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
