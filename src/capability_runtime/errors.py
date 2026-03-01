from __future__ import annotations

"""框架统一错误定义。"""

from .protocol.context import RecursionLimitError


class RuntimeFrameworkError(Exception):
    """框架基础错误。"""


class CapabilityNotFoundError(RuntimeFrameworkError):
    """指定 ID 的能力未注册。"""


__all__ = [
    "RuntimeFrameworkError",
    "CapabilityNotFoundError",
    "RecursionLimitError",
]
