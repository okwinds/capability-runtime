from __future__ import annotations

"""
升级护栏（skills-runtime-sdk==0.1.9）：
- 上游将 `ChatBackend` 协议显式收敛到 `skills_runtime.llm.protocol`，并对
  `stream_chat(request: ChatRequest)` 做 fail-fast 校验；
- 本仓 `AgentlyChatBackend` 必须继续满足该协议，避免升级后在 Agent 初始化期直接崩溃。
"""

from skills_runtime.llm.chat_sse import ChatStreamEvent
from skills_runtime.llm.protocol import ChatRequest

from capability_runtime.adapters.agently_backend import AgentlyBackendConfig, AgentlyChatBackend
from capability_runtime.sdk_lifecycle import (
    _ModelOverrideBackend,
    _ResponseFormatOverrideBackend,
    _ToolChoiceOverrideBackend,
    _UsageTapBackend,
)


class _DummyRequester:
    def generate_request_data(self) -> object:
        class _Req:
            data: dict = {}
            request_options: dict = {}
            stream: bool = False

        return _Req()

    async def request_model(self, request_data: object):
        yield ("message", "[DONE]")


def _dummy_requester_factory() -> _DummyRequester:
    return _DummyRequester()


def test_agently_chat_backend_satisfies_upstream_chat_backend_protocol() -> None:
    from skills_runtime.llm.protocol import _validate_chat_backend_protocol

    backend = AgentlyChatBackend(config=AgentlyBackendConfig(requester_factory=_dummy_requester_factory))
    _validate_chat_backend_protocol(backend)


class _WrapperDummyBackend:
    async def stream_chat(self, request: ChatRequest):
        _ = request
        if False:
            yield ChatStreamEvent(type="message", text="")


def test_backend_wrapper_chain_satisfies_upstream_chat_backend_protocol() -> None:
    """
    升级护栏：runtime 实际注入给上游 Agent 的不是裸 backend，而是一串 wrapper。
    这些 wrapper 也必须继续满足上游 ChatBackend protocol。
    """

    from skills_runtime.llm.protocol import _validate_chat_backend_protocol

    backend = _WrapperDummyBackend()
    wrapped = _ModelOverrideBackend(backend=backend, model="gpt-test")
    wrapped = _ToolChoiceOverrideBackend(backend=wrapped, tool_choice={"type": "auto"})
    wrapped = _ResponseFormatOverrideBackend(
        backend=wrapped,
        response_format={"type": "json_schema", "json_schema": {"name": "demo", "schema": {"type": "object"}}},
    )
    wrapped = _UsageTapBackend(backend=wrapped)

    _validate_chat_backend_protocol(wrapped)
