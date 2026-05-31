from __future__ import annotations

import pytest

from capability_runtime.adapters.agently_backend import AgentlyBackendConfig, AgentlyChatBackend
from skills_runtime.llm.protocol import ChatRequest
from skills_runtime.tools.protocol import ToolSpec


class _FakeRequestData:
    def __init__(self) -> None:
        self.data = {"input": []}
        self.request_options = {}
        self.request_url = "http://example.invalid/responses"
        self.headers = {}
        self.client_options = {}
        self.stream = True


class _FakeResponsesRequester:
    def __init__(self, items):
        self._items = list(items)
        self.last_request_data = None

    def generate_request_data(self):
        return _FakeRequestData()

    async def request_model(self, request_data):
        self.last_request_data = request_data
        for item in self._items:
            yield item


def _responses_backend(requester: _FakeResponsesRequester) -> AgentlyChatBackend:
    return AgentlyChatBackend(
        config=AgentlyBackendConfig(
            requester_factory=lambda: requester,
            requester_strategy="responses",
        )
    )


@pytest.mark.asyncio
async def test_responses_bridge_emits_text_tool_calls_usage_and_completed_in_order() -> None:
    usage_events = []
    requester = _FakeResponsesRequester(
        [
            (
                "response.output_text.delta",
                '{"type":"response.output_text.delta","delta":"hello"}',
            ),
            (
                "response.output_item.done",
                '{"type":"response.output_item.done","output_index":0,"item":{"type":"function_call","call_id":"call_lookup","name":"lookup","arguments":"{\\"query\\":\\"caprt\\"}"}}',
            ),
            (
                "response.completed",
                '{"type":"response.completed","response":{"id":"resp_123","model":"gpt-responses","status":"completed","output":[{"type":"function_call","call_id":"call_lookup","name":"lookup","arguments":"{\\"query\\":\\"caprt\\"}"}],"usage":{"input_tokens":3,"output_tokens":5,"total_tokens":8}}}',
            ),
        ]
    )
    backend = _responses_backend(requester)

    out = [
        ev
        async for ev in backend.stream_chat(
            ChatRequest(
                model="gpt-responses",
                messages=[{"role": "user", "content": "x"}],
                tools=[],
                extra={"_caprt_usage_sink": usage_events.append},
            )
        )
    ]

    assert [ev.type for ev in out] == ["text_delta", "tool_calls", "completed"]
    assert out[0].text == "hello"
    assert out[1].tool_calls is not None
    assert out[1].tool_calls[0].call_id == "call_lookup"
    assert out[1].tool_calls[0].name == "lookup"
    assert out[1].tool_calls[0].args == {"query": "caprt"}
    assert out[2].request_id == "resp_123"
    assert out[2].provider == "openai-responses"
    assert out[2].usage == {"input_tokens": 3, "output_tokens": 5, "total_tokens": 8}
    assert usage_events == [
        {
            "model": "gpt-responses",
            "input_tokens": 3,
            "output_tokens": 5,
            "total_tokens": 8,
            "request_id": "resp_123",
            "provider": "openai-responses",
        }
    ]


@pytest.mark.asyncio
async def test_responses_bridge_usage_falls_back_to_request_model_when_provider_omits_model() -> None:
    usage_events = []
    requester = _FakeResponsesRequester(
        [
            (
                "response.completed",
                '{"type":"response.completed","response":{"id":"resp_no_model","status":"completed","output":[],"usage":{"input_tokens":4,"output_tokens":5,"total_tokens":9}}}',
            ),
        ]
    )
    backend = _responses_backend(requester)

    out = [
        ev
        async for ev in backend.stream_chat(
            ChatRequest(
                model="gpt-5.4",
                messages=[{"role": "user", "content": "x"}],
                tools=[],
                extra={"_caprt_usage_sink": usage_events.append},
            )
        )
    ]

    assert [ev.type for ev in out] == ["completed"]
    assert out[0].request_id == "resp_no_model"
    assert out[0].provider == "openai-responses"
    assert usage_events == [
        {
            "model": "gpt-5.4",
            "input_tokens": 4,
            "output_tokens": 5,
            "total_tokens": 9,
            "request_id": "resp_no_model",
            "provider": "openai-responses",
        }
    ]


@pytest.mark.asyncio
async def test_responses_bridge_accumulates_function_call_argument_deltas_before_done() -> None:
    requester = _FakeResponsesRequester(
        [
            (
                "response.output_item.added",
                '{"type":"response.output_item.added","output_index":0,"item":{"type":"function_call","call_id":"call_write","name":"file_write"}}',
            ),
            (
                "response.function_call_arguments.delta",
                '{"type":"response.function_call_arguments.delta","output_index":0,"call_id":"call_write","delta":"{\\"path\\":\\"a.txt\\","}',
            ),
            (
                "response.function_call_arguments.delta",
                '{"type":"response.function_call_arguments.delta","output_index":0,"call_id":"call_write","delta":"\\"content\\":\\"ok\\"}"}',
            ),
            (
                "response.output_item.done",
                '{"type":"response.output_item.done","output_index":0,"item":{"type":"function_call","call_id":"call_write","name":"file_write","arguments":"{\\"path\\":\\"a.txt\\",\\"content\\":\\"ok\\"}"}}',
            ),
            (
                "response.completed",
                '{"type":"response.completed","response":{"id":"resp_tool","model":"gpt-responses","status":"completed","output":[],"usage":{"input_tokens":1,"output_tokens":1,"total_tokens":2}}}',
            ),
        ]
    )
    backend = _responses_backend(requester)

    out = [
        ev
        async for ev in backend.stream_chat(ChatRequest(model="gpt-responses", messages=[{"role": "user", "content": "x"}], tools=[]))
    ]

    tool_events = [ev for ev in out if ev.type == "tool_calls"]
    assert len(tool_events) == 1
    call = tool_events[0].tool_calls[0]
    assert call.call_id == "call_write"
    assert call.name == "file_write"
    assert call.args == {"path": "a.txt", "content": "ok"}
    assert out[-1].type == "completed"


@pytest.mark.asyncio
async def test_responses_bridge_writes_responses_input_and_flattened_tools() -> None:
    requester = _FakeResponsesRequester(
        [
            (
                "response.completed",
                '{"type":"response.completed","response":{"id":"resp_done","model":"gpt-responses","status":"completed","output":[]}}',
            )
        ]
    )
    backend = _responses_backend(requester)

    tool_spec = ToolSpec(
        name="lookup",
        description="lookup docs",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        requires_approval=False,
    )

    _ = [
        ev
        async for ev in backend.stream_chat(
            ChatRequest(
                model="gpt-responses",
                messages=[{"role": "user", "content": "hello"}],
                tools=[tool_spec],
            )
        )
    ]

    assert requester.last_request_data is not None
    assert requester.last_request_data.data["input"] == [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hello"}]}
    ]
    assert requester.last_request_data.request_options["tools"] == [
        {
            "type": "function",
            "name": "lookup",
            "description": "lookup docs",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            "strict": False,
        }
    ]


@pytest.mark.asyncio
async def test_responses_bridge_maps_tool_loop_messages_to_response_items() -> None:
    """
    Responses mode 必须把 tool loop 的 assistant tool_calls / tool response 映射为 Responses items。
    """

    requester = _FakeResponsesRequester(
        [
            (
                "response.completed",
                '{"type":"response.completed","response":{"id":"resp_done","model":"gpt-responses","status":"completed","output":[]}}',
            )
        ]
    )
    backend = _responses_backend(requester)

    _ = [
        ev
        async for ev in backend.stream_chat(
            ChatRequest(
                model="gpt-responses",
                messages=[
                    {"role": "user", "content": "lookup"},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_lookup",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": '{"query":"caprt"}'},
                            }
                        ],
                    },
                    {"role": "tool", "tool_call_id": "call_lookup", "content": '{"result":"ok"}'},
                ],
                tools=[],
            )
        )
    ]

    assert requester.last_request_data is not None
    assert requester.last_request_data.data["input"] == [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "lookup"}]},
        {
            "type": "function_call",
            "call_id": "call_lookup",
            "name": "lookup",
            "arguments": '{"query":"caprt"}',
        },
        {"type": "function_call_output", "call_id": "call_lookup", "output": '{"result":"ok"}'},
    ]
