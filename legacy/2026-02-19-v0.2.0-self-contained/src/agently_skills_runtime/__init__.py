"""
agently-skills-runtime（v0.2.0 主线）

本包提供一个“面向能力（Capability-oriented）”的运行时框架：
- 协议层（protocol/）：纯 dataclass/Enum 的能力声明与执行上下文；不依赖上游。
- 运行时（runtime/）：能力注册、依赖校验、递归/循环守卫与执行分发；不依赖上游。
- 适配器（adapters/）：桥接上游能力（可依赖上游，但只使用 Public API）。

注意：
- 本仓库主线为破坏式升级（v0.2.0），旧 bridge-only 实现已归档到 `legacy/`。
"""

from .protocol.agent import AgentIOSchema, AgentSpec
from .protocol.capability import (
    CapabilityKind,
    CapabilityRef,
    CapabilityResult,
    CapabilitySpec,
    CapabilityStatus,
)
from .protocol.context import ExecutionContext, RecursionLimitError
from .protocol.skill import SkillDispatchRule, SkillSpec
from .protocol.workflow import (
    ConditionalStep,
    InputMapping,
    LoopStep,
    ParallelStep,
    Step,
    WorkflowSpec,
    WorkflowStep,
)
from .runtime.engine import CapabilityRuntime, RuntimeConfig
from .runtime.guards import LoopBreakerError
from .runtime.registry import CapabilityRegistry

__all__ = [
    # Protocol
    "CapabilitySpec",
    "CapabilityKind",
    "CapabilityRef",
    "CapabilityResult",
    "CapabilityStatus",
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
    # Runtime
    "CapabilityRuntime",
    "RuntimeConfig",
    "CapabilityRegistry",
    "LoopBreakerError",
]
