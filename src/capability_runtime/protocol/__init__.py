from __future__ import annotations

"""Protocol 层：纯能力类型定义，不依赖任何上游模块。"""

from .agent import AgentIOSchema, AgentSpec, PromptRenderMode
from .capability import (
    CapabilityKind,
    CapabilityRef,
    CapabilityResult,
    CapabilitySpec,
    CapabilityStatus,
)
from .chat_backend import ChatBackendProtocol
from .context import ExecutionContext, RecursionLimitError
from .workflow import (
    ConditionalStep,
    InputMapping,
    LoopStep,
    ParallelStep,
    Step,
    WorkflowSpec,
    WorkflowStep,
)

__all__ = [
    "CapabilityKind",
    "CapabilityRef",
    "CapabilitySpec",
    "CapabilityStatus",
    "CapabilityResult",
    "AgentSpec",
    "AgentIOSchema",
    "PromptRenderMode",
    "ChatBackendProtocol",
    "WorkflowSpec",
    "Step",
    "LoopStep",
    "ParallelStep",
    "ConditionalStep",
    "InputMapping",
    "WorkflowStep",
    "ExecutionContext",
    "RecursionLimitError",
]
