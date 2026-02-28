"""capability-runtime: 桥接胶水层 + 能力组织层。"""
from __future__ import annotations

# === 桥接层导出（保持向后兼容）===
from .bridge import Runtime, RuntimeConfig
from .config import BridgeConfigModel
from .types import NodeReportV2, NodeResultV2

# === Protocol 导出 ===
from .protocol.agent import AgentIOSchema, AgentSpec
from .protocol.capability import (
    CapabilityKind,
    CapabilityRef,
    CapabilityResult,
    CapabilitySpec,
    CapabilityStatus,
)
from .protocol.context import ExecutionContext, RecursionLimitError
from .protocol.workflow import (
    ConditionalStep,
    InputMapping,
    LoopStep,
    ParallelStep,
    Step,
    WorkflowSpec,
    WorkflowStep,
)

# === Runtime 导出 ===
from .runtime.engine import AdapterProtocol, CapabilityRuntime, RuntimeConfig
from .runtime.guards import ExecutionGuards, LoopBreakerError
from .runtime.loop import LoopController
from .runtime.registry import CapabilityRegistry

# === Adapter 导出 ===
from .adapters.agent_adapter import AgentAdapter
from .adapters.workflow_adapter import WorkflowAdapter

# === 错误导出 ===
from .errors import AdapterNotFoundError, RuntimeFrameworkError, CapabilityNotFoundError

__all__ = [
    # Bridge
    "Runtime",
    "RuntimeConfig",
    "NodeReportV2",
    "NodeResultV2",
    "BridgeConfigModel",
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
    "WorkflowStep",
    "ExecutionContext",
    "RecursionLimitError",
    # Runtime
    "CapabilityRuntime",
    "RuntimeConfig",
    "AdapterProtocol",
    "CapabilityRegistry",
    "ExecutionGuards",
    "LoopBreakerError",
    "LoopController",
    # Adapters
    "AgentAdapter",
    "WorkflowAdapter",
    # Errors
    "RuntimeFrameworkError",
    "AdapterNotFoundError",
    "CapabilityNotFoundError",
]
