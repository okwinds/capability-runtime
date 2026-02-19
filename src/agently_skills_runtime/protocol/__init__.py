from __future__ import annotations

"""Protocol 层：纯能力类型定义，不依赖任何上游模块。"""

from .agent import AgentIOSchema, AgentSpec
from .capability import (
    CapabilityKind,
    CapabilityRef,
    CapabilityResult,
    CapabilitySpec,
    CapabilityStatus,
)
from .context import ExecutionContext, RecursionLimitError
from .skill import SkillDispatchRule, SkillSpec
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
    "SkillSpec",
    "SkillDispatchRule",
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
]
