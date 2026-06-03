from __future__ import annotations

"""
统一运行时配置（RuntimeConfig）。

说明：
- 本仓定位为 runtime/adapter/bridge 的契约收敛层；
- 业务不应在本仓中被定义或侵入；
- 执行模式通过 `RuntimeConfig.mode` 切换，而不是通过更换入口类。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Literal, Optional, Protocol


PreflightMode = Literal["error", "warn", "off"]
RuntimeMode = Literal["mock", "bridge", "sdk_native"]
OutputValidationMode = Literal["off", "warn", "error"]
ProviderRequesterStrategy = Literal["chat_completions", "responses"]
AgentlyRequesterStrategy = ProviderRequesterStrategy
ToolChoiceAfterToolResult = Literal["none", "auto"]


class ProviderRequester(Protocol):
    """Runtime-owned provider requester shape used by bridge transport adapters."""

    def generate_request_data(self) -> Any:
        """Return a mutable request data object consumed by the bridge adapter."""

        ...

    def request_model(self, request_data: Any) -> AsyncIterator[tuple[str, Any]] | Awaitable[AsyncIterator[tuple[str, Any]]]:
        """Execute a model request and return provider stream events."""

        ...


class ProviderRequesterFactory(Protocol):
    """Factory for creating provider requesters without exposing provider-native agent objects."""

    requester_strategy: ProviderRequesterStrategy

    def __call__(self) -> ProviderRequester:
        """Create a provider requester instance."""

        ...


@dataclass(frozen=True)
class CustomTool:
    """
    预注册的自定义工具（每次创建 SDK Agent 时注入）。

    参数：
    - spec：工具规格（ToolSpec）
    - handler：工具处理函数（签名需兼容上游 ToolRegistry）
    - override：是否允许覆盖同名工具
    - descriptor：可选上游 tool descriptor（若注册签名支持则透传）
    """

    spec: Any
    handler: Any
    override: bool = False
    descriptor: Any | None = None


@dataclass(frozen=True)
class RuntimeConfig:
    """
    统一运行时配置。

    参数分组：
    - 执行模式：mode
    - 桥接执行：workspace_root / sdk_config_paths / provider_requester_factory /
      requester_strategy / agently_agent（legacy 兼容）
    - Workflow：workflow_engine（可注入）
    - SDK 注入：approval_provider / human_io / cancel_checker / wal_backend / env_vars
    - Skills 配置：skills_config / in_memory_skills
    - 自定义工具：custom_tools
    - 护栏：max_depth / max_total_loop_iterations / preflight_mode
    - Mock：mock_handler
    - 观测：on_event
    """

    # === 执行模式 ===
    mode: RuntimeMode = "bridge"

    # === 桥接配置（mode=bridge 时使用）===
    workspace_root: Optional[Path] = None
    sdk_config_paths: List[Path] = field(default_factory=list)
    provider_requester_factory: Optional[ProviderRequesterFactory] = None
    agently_agent: Optional[Any] = None
    requester_strategy: Optional[ProviderRequesterStrategy] = None
    agently_requester: Optional[AgentlyRequesterStrategy] = None
    # 显式兼容开关：工具结果回注后的后续 LLM 请求是否覆写 tool_choice。
    # 默认 None 表示保持 AgentSpec.llm_config["tool_choice"] 原样透传。
    tool_choice_after_tool_result: Optional[ToolChoiceAfterToolResult] = None

    @property
    def effective_requester_strategy(self) -> ProviderRequesterStrategy:
        """
        返回当前 Runtime bridge requester strategy。

        `requester_strategy` 是中立首选字段；`agently_requester` 保留为旧配置兼容入口。
        """

        return self.requester_strategy or "chat_completions"

    def __post_init__(self) -> None:
        """运行时配置枚举值校验，避免非法 opt-in 值穿透到 provider。"""

        if self.requester_strategy not in (None, "chat_completions", "responses"):
            raise ValueError("requester_strategy must be one of: 'chat_completions', 'responses'")
        if self.agently_requester not in (None, "chat_completions", "responses"):
            raise ValueError("agently_requester must be one of: None, 'chat_completions', 'responses'")
        if self.requester_strategy is not None and self.agently_requester is not None and self.agently_requester != self.requester_strategy:
            raise ValueError("agently_requester conflicts with requester_strategy")
        effective_strategy = self.requester_strategy or self.agently_requester or "chat_completions"
        object.__setattr__(self, "requester_strategy", effective_strategy)
        if self.provider_requester_factory is not None:
            factory_strategy = getattr(self.provider_requester_factory, "requester_strategy", None)
            if factory_strategy is None:
                raise ValueError("provider_requester_factory must expose requester_strategy")
            if factory_strategy not in ("chat_completions", "responses"):
                raise ValueError("provider_requester_factory requester_strategy must be one of: 'chat_completions', 'responses'")
            if factory_strategy != self.effective_requester_strategy:
                raise ValueError(
                    "provider_requester_factory requester_strategy conflicts with RuntimeConfig.requester_strategy"
                )
        if self.tool_choice_after_tool_result not in (None, "none", "auto"):
            raise ValueError("tool_choice_after_tool_result must be one of: None, 'none', 'auto'")

    # === Workflow 引擎注入（可选）===
    #
    # 说明：
    # - 默认使用 TriggerFlowWorkflowEngine（Agently TriggerFlow）；
    # - 当上游 workflow engine 需要替换/隔离时，可注入兼容接口的实现：
    #   - execute(*, spec, input, context, runtime) -> CapabilityResult
    #   - execute_stream(*, spec, input, context, runtime) -> AsyncIterator[WorkflowStreamItem]
    workflow_engine: Optional[Any] = None

    # === 可选 Runtime RPC client/server 注入（v1）===
    #
    # 说明：
    # - `runtime_client`：供 RuntimeServiceFacade 在 RPC 执行目标下使用；
    # - `runtime_server`：供 Runtime.bind_runtime_server() 显式绑定本地 Runtime；
    # - 两者均采用 duck typing，不在 RuntimeConfig 层做强类型约束。
    runtime_client: Optional[Any] = None
    runtime_server: Optional[Any] = None

    # === SDK 注入 ===
    approval_provider: Optional[Any] = None
    human_io: Optional[Any] = None
    cancel_checker: Optional[Callable[[], bool]] = None
    exec_sessions: Optional[Any] = None
    collab_manager: Optional[object] = None
    wal_backend: Optional[Any] = None
    env_vars: Dict[str, str] = field(default_factory=dict)

    # === SDK LLM backend 注入（离线回归/测试）===
    #
    # 说明：
    # - 默认情况下 backend 由 mode 决定：
    #   - bridge：AgentlyChatBackend（复用 OpenAICompatible requester 作为传输层）
    #   - sdk_native：skills_runtime 原生 OpenAIChatCompletionsBackend
    # - 当你需要离线可回归（不依赖外网/真实 key），可注入 FakeChatBackend 等实现驱动真实 Agent loop，
    #   以获得完整的 tool/approvals/WAL/NodeReport 证据链。
    # - 该字段仅改变“LLM 传输层”，不改变 tool/skills/WAL 的执行真相源（仍为 skills_runtime.Agent）。
    sdk_backend: Optional[Any] = None

    # === Skills 配置 ===
    skills_config: Optional[Dict[str, Any]] = None
    in_memory_skills: Optional[Dict[str, List[dict]]] = None

    # === 自定义 Tools ===
    custom_tools: List[CustomTool] = field(default_factory=list)

    # === 护栏 ===
    max_depth: int = 10
    max_dynamic_nodes: int = 64
    max_total_loop_iterations: int = 50000
    preflight_mode: PreflightMode = "error"

    # === Output Validator（可选）===
    #
    # 说明：
    # - 取代旧的 SchemaGate/SchemaGateMode：以 callback 方式提供输出校验；
    # - callback 返回值应是“可观测摘要”，不得把大段 payload 原文塞入 meta；
    # - 推荐签名（keyword-only）：
    #   validate(*, final_output: str, node_report: NodeReport, context: dict) -> dict
    output_validation_mode: OutputValidationMode = "off"
    output_validator: Optional[Callable[..., Any]] = None

    # === Mock（mode=mock 时使用）===
    #
    # 说明：
    # - 用于离线回归与场景测试；
    # - 允许两种签名（二选一）：
    #   1) handler(spec, input_dict) -> Any | CapabilityResult
    #   2) handler(spec, input_dict, context) -> Any | CapabilityResult
    # - 返回 CapabilityResult 时 Runtime 将直接透传（便于测试 pending/failed/report 语义）。
    mock_handler: Optional[Callable[..., Any]] = None

    # === 事件回调（可观测性）===
    #
    # 说明：
    # - 允许两种签名（二选一）：
    #   1) on_event(event) -> None
    #   2) on_event(event, context) -> None
    # - 回调异常将被吞掉（fail-open），避免影响主流程。
    on_event: Optional[Callable[..., None]] = None


def normalize_workspace_root(workspace_root: Optional[Path]) -> Path:
    """
    归一化 workspace_root。

    参数：
    - workspace_root：可选 Path；为 None 时默认当前目录

    返回：
    - 绝对路径 Path
    """

    return (workspace_root or Path(".")).expanduser().resolve()


__all__ = [
    "PreflightMode",
    "RuntimeMode",
    "OutputValidationMode",
    "ProviderRequesterStrategy",
    "AgentlyRequesterStrategy",
    "ToolChoiceAfterToolResult",
    "ProviderRequester",
    "ProviderRequesterFactory",
    "CustomTool",
    "RuntimeConfig",
    "normalize_workspace_root",
]
