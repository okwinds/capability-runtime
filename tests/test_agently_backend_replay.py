import pytest

from agently_skills_runtime.adapters.agently_backend import AgentlyBackendConfig, AgentlyChatBackend
from agent_sdk.llm.protocol import ChatRequest


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
        for item in self._items:
            yield item


def _backend_from_items(items):
    def factory():
        return _FakeRequester(items)

    return AgentlyChatBackend(config=AgentlyBackendConfig(requester_factory=factory))


@pytest.mark.asyncio
async def test_backend_emits_text_delta_and_completed_on_stop_finish_reason():
    backend = _backend_from_items(
        [
            (
                "message",
                '{"choices":[{"delta":{"content":"hi"},"finish_reason":null}]}',
            ),
            (
                "message",
                '{"choices":[{"delta":{"content":"!"},"finish_reason":"stop"}]}',
            ),
        ]
    )

    out = []
    async for ev in backend.stream_chat(ChatRequest(model="m", messages=[{"role": "user", "content": "x"}], tools=[])):
        out.append(ev)

    assert [e.type for e in out] == ["text_delta", "text_delta", "completed"]
    assert "".join([e.text or "" for e in out if e.type == "text_delta"]) == "hi!"


@pytest.mark.asyncio
async def test_backend_emits_completed_on_done_sentinel():
    backend = _backend_from_items(
        [
            ("message", '{"choices":[{"delta":{"content":"ok"},"finish_reason":null}]}'),
            ("message", "[DONE]"),
        ]
    )

    out = [ev async for ev in backend.stream_chat(ChatRequest(model="m", messages=[{"role": "user", "content": "x"}], tools=[]))]
    assert out[-1].type == "completed"


@pytest.mark.asyncio
async def test_backend_flushes_tool_calls_on_finish_reason_tool_calls():
    backend = _backend_from_items(
        [
            (
                "message",
                '{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"shell_exec","arguments":"{\\"argv\\":[\\"echo\\""}}]},"finish_reason":null}]}',
            ),
            (
                "message",
                '{"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":",\\"hi\\"]}"}}]},"finish_reason":null}]}',
            ),
            ("message", '{"choices":[{"delta":{},"finish_reason":"tool_calls"}]}'),
            ("message", "[DONE]"),
        ]
    )

    out = [ev async for ev in backend.stream_chat(ChatRequest(model="m", messages=[{"role": "user", "content": "x"}], tools=[]))]
    tool_events = [e for e in out if e.type == "tool_calls"]
    assert len(tool_events) == 1
    calls = tool_events[0].tool_calls or []
    assert len(calls) == 1
    assert calls[0].call_id == "call_1"
    assert calls[0].name == "shell_exec"
    assert calls[0].args["argv"] == ["echo", "hi"]


@pytest.mark.asyncio
async def test_backend_flushes_tool_calls_on_done_when_no_finish_reason():
    backend = _backend_from_items(
        [
            (
                "message",
                '{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"file_write","arguments":"{\\"path\\":\\"a.txt\\","}}]},"finish_reason":null}]}',
            ),
            (
                "message",
                '{"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"content\\":\\"x\\"}"}}]},"finish_reason":null}]}',
            ),
            ("message", "[DONE]"),
        ]
    )

    out = [ev async for ev in backend.stream_chat(ChatRequest(model="m", messages=[{"role": "user", "content": "x"}], tools=[]))]
    tool_events = [e for e in out if e.type == "tool_calls"]
    assert len(tool_events) == 1
    assert tool_events[0].tool_calls[0].name == "file_write"


@pytest.mark.asyncio
async def test_backend_handles_tool_calls_missing_index_by_allocating():
    backend = _backend_from_items(
        [
            (
                "message",
                '{"choices":[{"delta":{"tool_calls":[{"id":"call_1","type":"function","function":{"name":"shell_exec","arguments":"{\\"argv\\":[\\"echo\\",\\"x\\"]}"}}]},"finish_reason":"tool_calls"}]}',
            ),
            ("message", "[DONE]"),
        ]
    )
    out = [ev async for ev in backend.stream_chat(ChatRequest(model="m", messages=[{"role": "user", "content": "x"}], tools=[]))]
    tool_events = [e for e in out if e.type == "tool_calls"]
    assert tool_events and tool_events[0].tool_calls[0].call_id == "call_1"


@pytest.mark.asyncio
async def test_backend_ignores_invalid_json_chunks():
    backend = _backend_from_items([("message", "{not-json"), ("message", "[DONE]")])
    out = [ev async for ev in backend.stream_chat(ChatRequest(model="m", messages=[{"role": "user", "content": "x"}], tools=[]))]
    assert out[-1].type == "completed"


@pytest.mark.asyncio
async def test_backend_ignores_non_string_data_items():
    backend = _backend_from_items([("message", {"not": "a string"}), ("message", "[DONE]")])
    out = [ev async for ev in backend.stream_chat(ChatRequest(model="m", messages=[{"role": "user", "content": "x"}], tools=[]))]
    assert out[-1].type == "completed"


@pytest.mark.asyncio
async def test_backend_raises_on_requester_error_event():
    backend = _backend_from_items([("error", RuntimeError("boom"))])
    with pytest.raises(RuntimeError, match="boom"):
        async for _ in backend.stream_chat(ChatRequest(model="m", messages=[{"role": "user", "content": "x"}], tools=[])):
            pass


@pytest.mark.asyncio
async def test_backend_calls_finish_when_stream_ends_without_done():
    backend = _backend_from_items([("message", '{"choices":[{"delta":{"content":"x"},"finish_reason":null}]}')])
    out = [ev async for ev in backend.stream_chat(ChatRequest(model="m", messages=[{"role": "user", "content": "x"}], tools=[]))]
    assert out[-1].type == "completed"
    assert any(e.finish_reason == "eof" for e in out if e.type == "completed")


@pytest.mark.asyncio
async def test_backend_does_not_send_empty_tools_field_when_tools_is_none():
    backend = _backend_from_items([("message", "[DONE]")])
    out = [ev async for ev in backend.stream_chat(ChatRequest(model="m", messages=[{"role": "user", "content": "x"}], tools=None))]
    assert out[-1].type == "completed"
