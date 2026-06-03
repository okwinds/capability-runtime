"""
ChatBackend 协议定义。

提供类型安全的 ChatBackend 接口，用于 backend wrapper 的静态类型检查。
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class ChatBackendProtocol(Protocol):
    """
    ChatBackend 协议：定义流式聊天后端的接口。

    说明：
    - 与 runtime 注入的 streaming chat backend shape 对齐
    - 用于 backend wrapper 的类型注解，减少 `Any` 使用
    """

    def stream_chat(self, request: Any) -> AsyncIterator[Any]:
        """
        发起流式聊天请求。

        参数：
        - request：本仓 runtime 传入的 chat request 兼容对象

        返回：
        - chat stream event 兼容对象的异步迭代器
        """
        ...


__all__ = ["ChatBackendProtocol"]
