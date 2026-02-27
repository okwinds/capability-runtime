"""agently-skills-runtime：统一 Runtime 入口（能力协议 + 执行 + 报告）。"""
from __future__ import annotations

# === 统一入口 ===
from .config import CustomTool, RuntimeConfig
from .runtime import Runtime

# === 报告类型 ===
from .types import NodeReport, NodeResult

# === Host toolkit（精选公共导出）===
from .host_toolkit import InvokeCapabilityAllowlist, make_invoke_capability_tool

# === Protocol 导出 ===
from .protocol.agent import AgentIOSchema, AgentSpec
from .protocol.capability import (
    CapabilityKind,
    CapabilityRef,
    CapabilityResult,
    CapabilitySpec,
    CapabilityStatus,
)
from .protocol.context import ExecutionContext
from .protocol.workflow import (
    ConditionalStep,
    InputMapping,
    LoopStep,
    ParallelStep,
    Step,
    WorkflowSpec,
)

# === 错误导出 ===
from .errors import AdapterNotFoundError, AgentlySkillsRuntimeError, CapabilityNotFoundError

__all__ = [
    # Runtime
    "Runtime",
    "RuntimeConfig",
    "CustomTool",
    # Reports
    "NodeReport",
    "NodeResult",
    # Host toolkit (selected)
    "InvokeCapabilityAllowlist",
    "make_invoke_capability_tool",
    # Protocol
    "CapabilityKind",
    "CapabilityRef",
    "CapabilitySpec",
    "CapabilityStatus",
    "CapabilityResult",
    "AgentSpec",
    "AgentIOSchema",
    "WorkflowSpec",
    "Step",
    "LoopStep",
    "ParallelStep",
    "ConditionalStep",
    "InputMapping",
    "ExecutionContext",
    # Errors
    "AgentlySkillsRuntimeError",
    "AdapterNotFoundError",
    "CapabilityNotFoundError",
]
