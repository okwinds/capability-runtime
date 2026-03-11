from __future__ import annotations

"""
升级护栏（skills-runtime-sdk==0.1.9）：
- 上游将 `ChatBackend` 协议显式收敛到 `skills_runtime.llm.protocol`，并对
  `stream_chat(request: ChatRequest)` 做 fail-fast 校验；
- 本仓 `AgentlyChatBackend` 必须继续满足该协议，避免升级后在 Agent 初始化期直接崩溃。
"""

from capability_runtime.adapters.agently_backend import AgentlyBackendConfig, AgentlyChatBackend


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
