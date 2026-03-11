import pytest

from capability_runtime.adapters.agently_backend import AgentlyBackendConfig, AgentlyChatBackend
from skills_runtime.llm.protocol import ChatRequest


class _FakeRequestData:
    def __init__(self):
        self.data = {"messages": []}
        self.request_options = {}
        self.request_url = "http://example.invalid"
        self.headers = {}
        self.client_options = {}
        self.stream = True


class _FakeRequester:
    def __init__(self, items):
        self._items = list(items)

    def generate_request_data(self):
        return _FakeRequestData()

    async def request_model(self, request_data):
        _ = request_data
        for item in self._items:
            yield item


def _backend_from_items(items):
    def factory():
        return _FakeRequester(items)

    return AgentlyChatBackend(config=AgentlyBackendConfig(requester_factory=factory))


@pytest.mark.asyncio
async def test_agently_backend_reports_usage_via_caprt_usage_sink():
    usage_events = []
    backend = _backend_from_items(
        [
            ("message", '{"choices":[{"delta":{"content":"ok"},"finish_reason":null}]}'),
            (
                "message",
                '{"choices":[{"delta":{},"finish_reason":"stop"}],"model":"bridge-usage-model","usage":{"prompt_tokens":11,"completion_tokens":7,"total_tokens":18}}',
            ),
            ("message", "[DONE]"),
        ]
    )

    out = [
        ev
        async for ev in backend.stream_chat(
            ChatRequest(
                model="m",
                messages=[{"role": "user", "content": "x"}],
                tools=[],
                extra={"_caprt_usage_sink": usage_events.append},
            )
        )
    ]

    assert [e.type for e in out] == ["text_delta", "completed"]
    assert usage_events == [
        {
            "model": "bridge-usage-model",
            "input_tokens": 11,
            "output_tokens": 7,
            "total_tokens": 18,
        }
    ]
