from __future__ import annotations

"""框架统一错误定义。"""

from .protocol.context import RecursionLimitError


class AgentlySkillsRuntimeError(Exception):
    """框架基础错误。"""


class AdapterNotFoundError(AgentlySkillsRuntimeError):
    """指定类型没有注册 Adapter。"""


class CapabilityNotFoundError(AgentlySkillsRuntimeError):
    """指定 ID 的能力未注册。"""


__all__ = [
    "AgentlySkillsRuntimeError",
    "AdapterNotFoundError",
    "CapabilityNotFoundError",
    "RecursionLimitError",
]
