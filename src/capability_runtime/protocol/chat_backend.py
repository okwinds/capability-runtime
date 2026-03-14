"""
ChatBackend 协议定义。

提供类型安全的 ChatBackend 接口，用于 backend wrapper 的静态类型检查。
"""

from __future__ import annotations

from typing import Any, AsyncGenerator, Protocol, runtime_checkable


@runtime_checkable
class ChatBackendProtocol(Protocol):
    """
    ChatBackend 协议：定义流式聊天后端的接口。

    说明：
    - 与 `skills_runtime.llm.protocol.ChatBackend` 对齐
    - 用于 backend wrapper 的类型注解，减少 `Any` 使用
    """

    def stream_chat(self, request: Any) -> AsyncGenerator[Any, None]:
        """
        发起流式聊天请求。

        参数：
        - request：ChatRequest 或兼容对象

        返回：
        - ChatStreamEvent 异步生成器
        """
        ...


__all__ = ["ChatBackendProtocol"]
