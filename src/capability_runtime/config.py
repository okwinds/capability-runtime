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
from typing import Any, Callable, Dict, List, Literal, Optional

from skills_runtime.core.exec_sessions import ExecSessionsProvider
from skills_runtime.llm.protocol import ChatBackend
from skills_runtime.safety.approvals import ApprovalProvider
from skills_runtime.state.wal_protocol import WalBackend
from skills_runtime.tools.protocol import HumanIOProvider, ToolSpec


PreflightMode = Literal["error", "warn", "off"]
RuntimeMode = Literal["mock", "bridge", "sdk_native"]
OutputValidationMode = Literal["off", "warn", "error"]


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

    spec: ToolSpec
    handler: Any
    override: bool = False
    descriptor: Any | None = None


@dataclass(frozen=True)
class RuntimeConfig:
    """
    统一运行时配置。

    参数分组：
    - 执行模式：mode
    - 桥接执行：workspace_root / sdk_config_paths / agently_agent
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
    agently_agent: Optional[Any] = None

    # === Workflow 引擎注入（可选）===
    #
    # 说明：
    # - 默认使用 TriggerFlowWorkflowEngine（Agently TriggerFlow）；
    # - 当上游 workflow engine 需要替换/隔离时，可注入兼容接口的实现：
    #   - execute(*, spec, input, context, runtime) -> CapabilityResult
    #   - execute_stream(*, spec, input, context, runtime) -> AsyncIterator[WorkflowStreamItem]
    workflow_engine: Optional[Any] = None

    # === SDK 注入 ===
    approval_provider: Optional[ApprovalProvider] = None
    human_io: Optional[HumanIOProvider] = None
    cancel_checker: Optional[Callable[[], bool]] = None
    exec_sessions: Optional[ExecSessionsProvider] = None
    collab_manager: Optional[object] = None
    wal_backend: Optional[WalBackend] = None
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
    sdk_backend: Optional[ChatBackend] = None

    # === Skills 配置 ===
    skills_config: Optional[Dict[str, Any]] = None
    in_memory_skills: Optional[Dict[str, List[dict]]] = None

    # === 自定义 Tools ===
    custom_tools: List[CustomTool] = field(default_factory=list)

    # === 护栏 ===
    max_depth: int = 10
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
