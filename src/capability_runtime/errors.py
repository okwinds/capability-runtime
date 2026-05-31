"""框架统一错误定义。"""

from __future__ import annotations

from .protocol.context import RecursionLimitError


class RuntimeFrameworkError(Exception):
    """框架基础错误。"""


class CapabilityNotFoundError(RuntimeFrameworkError):
    """指定 ID 的能力未注册。"""


class ProviderStreamTerminalError(RuntimeFrameworkError):
    """Provider stream returned a non-success terminal state."""

    def __init__(
        self,
        *,
        message: str,
        status: str,
        reason: str,
        completion_reason: str,
        error_code: str,
        request_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.reason = reason
        self.completion_reason = completion_reason
        self.error_code = error_code
        self.request_id = request_id
        self.provider = provider
        self.model = model

    def __str__(self) -> str:
        return self.message

    def to_control_payload(self) -> dict[str, str | None]:
        """返回 runtime control-plane 使用的 provider terminal 结构化审计载荷。"""

        return {
            "message": self.message,
            "status": self.status,
            "reason": self.reason,
            "completion_reason": self.completion_reason,
            "error_code": self.error_code,
            "request_id": self.request_id,
            "provider": self.provider,
            "model": self.model,
        }


__all__ = [
    "RuntimeFrameworkError",
    "CapabilityNotFoundError",
    "ProviderStreamTerminalError",
    "RecursionLimitError",
]
