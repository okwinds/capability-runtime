"""capability-runtime：统一 Runtime 入口（能力协议 + 执行 + 报告）。"""
from __future__ import annotations

__version__ = "0.1.1"

# === 统一入口 ===
from .config import CustomTool, RuntimeConfig
from .runtime import Runtime
from .service_facade import RuntimeServiceFacade, RuntimeServiceHandle, RuntimeServiceRequest, RuntimeSession
from .structured_stream import StructuredStreamEvent

# === 报告类型 ===
from .types import NodeReport, NodeResult

# === Host toolkit（精选公共导出）===
from .host_toolkit import InvokeCapabilityAllowlist, make_invoke_capability_tool
from .host_protocol import ApprovalTicket, HostRunSnapshot, HostRunStatus, ResumeIntent
from .manifest import CapabilityDescriptor, CapabilityManifestEntry, CapabilityVisibility

# === Protocol 导出 ===
from .protocol.agent import AgentIOSchema, AgentSpec, PromptRenderMode
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
from .services import RuntimeServices
from .workflow_runtime import WorkflowReplayRequest, WorkflowRunSnapshot, WorkflowRunStatus, WorkflowStepSnapshot

# === 错误导出 ===
from .errors import CapabilityNotFoundError, RuntimeFrameworkError

__all__ = [
    # Runtime
    "Runtime",
    "RuntimeConfig",
    "CustomTool",
    "StructuredStreamEvent",
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
    "CapabilityManifestEntry",
    "CapabilityDescriptor",
    "CapabilityVisibility",
    "HostRunStatus",
    "ApprovalTicket",
    "ResumeIntent",
    "HostRunSnapshot",
    "WorkflowRunStatus",
    "WorkflowStepSnapshot",
    "WorkflowRunSnapshot",
    "WorkflowReplayRequest",
    "RuntimeSession",
    "RuntimeServiceRequest",
    "RuntimeServiceHandle",
    "RuntimeServiceFacade",
    "AgentSpec",
    "AgentIOSchema",
    "PromptRenderMode",
    "WorkflowSpec",
    "Step",
    "LoopStep",
    "ParallelStep",
    "ConditionalStep",
    "InputMapping",
    "ExecutionContext",
    "RuntimeServices",
    # Errors
    "RuntimeFrameworkError",
    "CapabilityNotFoundError",
]
