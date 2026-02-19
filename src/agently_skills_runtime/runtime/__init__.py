"""Runtime 层：能力注册、执行守卫、循环控制、调度引擎。"""
from __future__ import annotations

from .engine import AdapterProtocol, CapabilityRuntime, RuntimeConfig
from .guards import ExecutionGuards, LoopBreakerError
from .loop import LoopController
from .registry import CapabilityRegistry

__all__ = [
    "CapabilityRegistry",
    "ExecutionGuards",
    "LoopBreakerError",
    "LoopController",
    "CapabilityRuntime",
    "RuntimeConfig",
    "AdapterProtocol",
]

