from __future__ import annotations

import pytest

from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec, Runtime, RuntimeConfig
from capability_runtime.adapters.agently_backend import (
    AgentlyBackendConfig,
    AgentlyChatBackend,
    build_openai_provider_requester_factory,
)
from capability_runtime.errors import ProviderStreamTerminalError
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


class _FakeResponsesRequesterWithNonStreamFallback:
    def __init__(self) -> None:
        self.last_request_data = None
        self.stream_values = []

    def generate_request_data(self):
        return _FakeRequestData()

    async def request_model(self, request_data):
        self.last_request_data = request_data
        self.stream_values.append(bool(request_data.stream))
        if request_data.stream:
            yield ("error", RuntimeError("async generator raised StopAsyncIteration"))
            return
        yield (
            "response.completed",
            '{"id":"resp_fallback","model":"gpt-responses","status":"completed","output_text":"fallback ok","output":[{"type":"function_call","call_id":"call_fallback","name":"lookup","arguments":"{\\"query\\":\\"fallback\\"}"}],"usage":{"input_tokens":2,"output_tokens":3,"total_tokens":5}}',
        )


class _FakeResponsesRequesterFactoryForFallbackIsolation:
    def __init__(self) -> None:
        self.requesters: list[Any] = []

    @property
    def requester_strategy(self) -> str:
        return "responses"

    def __call__(self):
        requester = _FakeResponsesRequesterWithNonStreamFallback()
        self.requesters.append(requester)
        return requester


class _FakeResponsesRequesterRaisesBeforeNonStreamFallback:
    def __init__(self) -> None:
        self.last_request_data = None
        self.stream_values = []

    def generate_request_data(self):
        return _FakeRequestData()

    async def request_model(self, request_data):
        self.last_request_data = request_data
        self.stream_values.append(bool(request_data.stream))
        if request_data.stream:
            raise RuntimeError("Error: Unknown Error\nDetail: async generator raised StopAsyncIteration")
        yield (
            "response.completed",
            '{"id":"resp_fallback_raise","model":"gpt-responses","status":"completed","output_text":"fallback ok","usage":{"input_tokens":2,"output_tokens":4,"total_tokens":6}}',
        )


class _FakeResponsesRequesterRaisesProviderErrorMentioningStopAsyncIteration:
    def __init__(self) -> None:
        self.stream_values = []

    def generate_request_data(self):
        return _FakeRequestData()

    async def request_model(self, request_data):
        self.stream_values.append(bool(request_data.stream))
        if request_data.stream:
            raise RuntimeError("provider auth failure mentioning StopAsyncIteration but not an empty stream")
        yield (
            "response.completed",
            '{"id":"masked_success","model":"gpt-responses","status":"completed","output_text":"masked success"}',
        )


class _FakeResponsesRequesterFallbackStatus:
    def __init__(self, status: str) -> None:
        self.status = status
        self.stream_values = []

    def generate_request_data(self):
        return _FakeRequestData()

    async def request_model(self, request_data):
        self.stream_values.append(bool(request_data.stream))
        if request_data.stream:
            raise RuntimeError("async generator raised StopAsyncIteration")
        yield (
            "response.completed",
            '{"id":"resp_bad_status","model":"gpt-responses","status":"'
            + self.status
            + '","error":{"code":"bad_status","message":"provider terminal"},"usage":{"input_tokens":1,"output_tokens":1,"total_tokens":2}}',
        )


class _FakeResponsesRequesterPartialThenFallback:
    def __init__(self, *, partial_kind: str) -> None:
        self.partial_kind = partial_kind
        self.stream_values = []

    def generate_request_data(self):
        return _FakeRequestData()

    async def request_model(self, request_data):
        self.stream_values.append(bool(request_data.stream))
        if request_data.stream:
            if self.partial_kind == "text":
                yield (
                    "response.output_text.delta",
                    '{"type":"response.output_text.delta","delta":"partial-"}',
                )
            else:
                yield (
                    "response.output_item.added",
                    '{"type":"response.output_item.added","output_index":0,"item":{"type":"function_call","call_id":"call_lookup","name":"lookup","arguments":"{}"}}',
                )
            yield ("error", RuntimeError("async generator raised StopAsyncIteration"))
            return
        yield (
            "response.completed",
            '{"id":"resp_should_not_be_used","model":"gpt-responses","status":"completed","output_text":"fallback ok"}',
        )


def _responses_backend(requester: _FakeResponsesRequester) -> AgentlyChatBackend:
    return AgentlyChatBackend(
        config=AgentlyBackendConfig(
            requester_factory=lambda: requester,
            requester_strategy="responses",
        )
    )


def _responses_backend_from_factory(factory: Any) -> AgentlyChatBackend:
    return AgentlyChatBackend(
        config=AgentlyBackendConfig(
            requester_factory=factory,
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
    assert out[2].provider is None
    assert out[2].usage == {"input_tokens": 3, "output_tokens": 5, "total_tokens": 8}
    assert usage_events == [
        {
            "model": "gpt-responses",
            "input_tokens": 3,
            "output_tokens": 5,
            "total_tokens": 8,
            "request_id": "resp_123",
            "provider": None,
            "provider_transport": "responses",
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
    assert out[0].provider is None
    assert usage_events == [
        {
            "model": "gpt-5.4",
            "input_tokens": 4,
            "output_tokens": 5,
            "total_tokens": 9,
            "request_id": "resp_no_model",
            "provider": None,
            "provider_transport": "responses",
        }
    ]


@pytest.mark.asyncio
async def test_responses_bridge_preserves_completed_metadata_when_usage_is_missing() -> None:
    """成功终态没有 token usage 时，request_id/model/provider evidence 仍要进入 usage sink。"""

    usage_events = []
    requester = _FakeResponsesRequester(
        [
            (
                "response.completed",
                '{"type":"response.completed","response":{"id":"resp_meta_only","model":"gpt-responses","provider":"provider-x","status":"completed","output":[]}}',
            ),
        ]
    )
    backend = _responses_backend(requester)

    out = [
        ev
        async for ev in backend.stream_chat(
            ChatRequest(
                model="request-model",
                messages=[{"role": "user", "content": "x"}],
                tools=[],
                extra={"_caprt_usage_sink": usage_events.append},
            )
        )
    ]

    assert [ev.type for ev in out] == ["completed"]
    assert out[0].request_id == "resp_meta_only"
    assert out[0].provider == "provider-x"
    assert out[0].usage is None
    assert usage_events == [
        {
            "model": "gpt-responses",
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "request_id": "resp_meta_only",
            "provider": "provider-x",
            "provider_transport": "responses",
        }
    ]


@pytest.mark.asyncio
async def test_responses_completed_does_not_duplicate_output_text_and_output_message() -> None:
    requester = _FakeResponsesRequester(
        [
            (
                "response.completed",
                '{"type":"response.completed","response":{"id":"resp_dupe","model":"gpt-responses","status":"completed","output_text":"same text","output":[{"type":"message","content":[{"type":"output_text","text":"same text"}]}]}}',
            ),
        ]
    )
    backend = _responses_backend(requester)

    out = [
        ev
        async for ev in backend.stream_chat(
            ChatRequest(model="gpt-responses", messages=[{"role": "user", "content": "x"}], tools=[])
        )
    ]

    assert [(ev.type, ev.text) for ev in out if ev.type == "text_delta"] == [("text_delta", "same text")]


@pytest.mark.asyncio
async def test_responses_stream_delta_and_completed_output_text_are_not_duplicated() -> None:
    """已经流式发出的文本不应在 completed.output_text 中整段重放。"""

    requester = _FakeResponsesRequester(
        [
            ("response.output_text.delta", '{"type":"response.output_text.delta","delta":"hel"}'),
            ("response.output_text.delta", '{"type":"response.output_text.delta","delta":"lo"}'),
            (
                "response.completed",
                '{"type":"response.completed","response":{"id":"resp_delta_done","model":"gpt-responses","status":"completed","output_text":"hello"}}',
            ),
        ]
    )
    backend = _responses_backend(requester)

    out = [
        ev
        async for ev in backend.stream_chat(
            ChatRequest(model="gpt-responses", messages=[{"role": "user", "content": "x"}], tools=[])
        )
    ]

    assert [(ev.type, ev.text) for ev in out if ev.type == "text_delta"] == [
        ("text_delta", "hel"),
        ("text_delta", "lo"),
    ]


@pytest.mark.asyncio
async def test_responses_stream_delta_and_completed_output_message_are_not_duplicated() -> None:
    """已经流式发出的文本不应在 completed.output message 中整段重放。"""

    requester = _FakeResponsesRequester(
        [
            ("response.output_text.delta", '{"type":"response.output_text.delta","delta":"hel"}'),
            ("response.output_text.delta", '{"type":"response.output_text.delta","delta":"lo"}'),
            (
                "response.completed",
                '{"type":"response.completed","response":{"id":"resp_delta_msg_done","model":"gpt-responses","status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":"hello"}]}]}}',
            ),
        ]
    )
    backend = _responses_backend(requester)

    out = [
        ev
        async for ev in backend.stream_chat(
            ChatRequest(model="gpt-responses", messages=[{"role": "user", "content": "x"}], tools=[])
        )
    ]

    assert [(ev.type, ev.text) for ev in out if ev.type == "text_delta"] == [
        ("text_delta", "hel"),
        ("text_delta", "lo"),
    ]


@pytest.mark.asyncio
async def test_responses_malformed_tool_arguments_fail_closed() -> None:
    """Responses tool arguments 非法时不能继续执行空参数 ToolCall。"""

    requester = _FakeResponsesRequester(
        [
            (
                "response.output_item.done",
                '{"type":"response.output_item.done","item":{"type":"function_call","call_id":"call_bad","name":"mutate","arguments":"not-json"}}',
            )
        ]
    )
    backend = _responses_backend(requester)

    with pytest.raises(ProviderStreamTerminalError) as exc_info:
        _ = [
            ev
            async for ev in backend.stream_chat(
                ChatRequest(model="gpt-responses", messages=[{"role": "user", "content": "x"}], tools=[])
            )
        ]

    assert exc_info.value.status == "failed"
    assert exc_info.value.reason == "malformed_tool_arguments"
    assert exc_info.value.provider_transport == "responses"


@pytest.mark.asyncio
async def test_responses_missing_tool_name_fail_closed() -> None:
    """Responses function_call 缺少 name 时不能继续下发空名 ToolCall。"""

    requester = _FakeResponsesRequester(
        [
            (
                "response.output_item.done",
                '{"type":"response.output_item.done","item":{"type":"function_call","call_id":"call_bad","name":"","arguments":"{}"}}',
            )
        ]
    )
    backend = _responses_backend(requester)

    with pytest.raises(ProviderStreamTerminalError) as exc_info:
        _ = [
            ev
            async for ev in backend.stream_chat(
                ChatRequest(model="gpt-responses", messages=[{"role": "user", "content": "x"}], tools=[])
            )
        ]

    assert exc_info.value.status == "failed"
    assert exc_info.value.reason == "malformed_tool_call"
    assert exc_info.value.error_code == "PROVIDER_TOOL_CALL_MALFORMED"
    assert exc_info.value.provider_transport == "responses"


@pytest.mark.asyncio
async def test_responses_missing_completed_tool_call_id_fail_closed() -> None:
    """Responses completed.output 的 function_call 缺 call_id 时必须 fail-closed。"""

    requester = _FakeResponsesRequester(
        [
            (
                "response.completed",
                '{"type":"response.completed","response":{"id":"resp_missing_call_id","model":"gpt-responses","status":"completed","output":[{"type":"function_call","name":"lookup","arguments":"{}"}],"usage":{"input_tokens":1,"output_tokens":1,"total_tokens":2}}}',
            )
        ]
    )
    backend = _responses_backend(requester)

    with pytest.raises(ProviderStreamTerminalError) as exc_info:
        _ = [
            ev
            async for ev in backend.stream_chat(
                ChatRequest(model="gpt-responses", messages=[{"role": "user", "content": "x"}], tools=[])
            )
        ]

    assert exc_info.value.status == "failed"
    assert exc_info.value.reason == "malformed_tool_call"
    assert exc_info.value.error_code == "PROVIDER_TOOL_CALL_MALFORMED"
    assert exc_info.value.provider_transport == "responses"


@pytest.mark.asyncio
async def test_responses_missing_streaming_tool_call_id_fail_closed() -> None:
    """Responses streaming function_call 缺 call_id 时不能静默丢弃。"""

    requester = _FakeResponsesRequester(
        [
            (
                "response.output_item.added",
                '{"type":"response.output_item.added","output_index":0,"item":{"type":"function_call","name":"lookup","arguments":"{}"}}',
            )
        ]
    )
    backend = _responses_backend(requester)

    with pytest.raises(ProviderStreamTerminalError) as exc_info:
        _ = [
            ev
            async for ev in backend.stream_chat(
                ChatRequest(model="gpt-responses", messages=[{"role": "user", "content": "x"}], tools=[])
            )
        ]

    assert exc_info.value.status == "failed"
    assert exc_info.value.reason == "malformed_tool_call"
    assert exc_info.value.error_code == "PROVIDER_TOOL_CALL_MALFORMED"
    assert exc_info.value.provider_transport == "responses"


@pytest.mark.asyncio
async def test_responses_bridge_passes_jsonable_extra_options() -> None:
    requester = _FakeResponsesRequester([("response.completed", '{"type":"response.completed","response":{"id":"resp_extra","status":"completed"}}')])
    backend = _responses_backend(requester)
    callback = lambda: None

    _ = [
        ev
        async for ev in backend.stream_chat(
            ChatRequest(
                model="gpt-responses",
                messages=[{"role": "user", "content": "x"}],
                tools=[],
                extra={
                    "metadata": {"trace_id": "trace-1"},
                    "parallel_tool_calls": False,
                    "_caprt_usage_sink": callback,
                    "on_retry": callback,
                },
            )
        )
    ]

    assert requester.last_request_data.request_options["metadata"] == {"trace_id": "trace-1"}
    assert requester.last_request_data.request_options["parallel_tool_calls"] is False
    assert "_caprt_usage_sink" not in requester.last_request_data.request_options
    assert "on_retry" not in requester.last_request_data.request_options


@pytest.mark.asyncio
async def test_responses_bridge_failed_terminal_event_fails_closed() -> None:
    requester = _FakeResponsesRequester(
        [
            (
                "response.failed",
                '{"type":"response.failed","response":{"id":"resp_failed","model":"gpt-responses","status":"failed","error":{"code":"model_error","message":"provider failed"}}}',
            )
        ]
    )
    backend = _responses_backend(requester)

    with pytest.raises(ProviderStreamTerminalError, match="provider failed"):
        _ = [
            ev
            async for ev in backend.stream_chat(
                ChatRequest(model="gpt-responses", messages=[{"role": "user", "content": "x"}], tools=[])
            )
        ]


@pytest.mark.asyncio
async def test_runtime_responses_failed_terminal_preserves_fail_closed_node_report(tmp_path) -> None:
    requester = _FakeResponsesRequester(
        [
            (
                "response.failed",
                '{"type":"response.failed","response":{"id":"resp_failed","model":"gpt-responses","status":"failed","error":{"code":"model_error","message":"provider failed"}}}',
            )
        ]
    )
    backend = _responses_backend(requester)
    runtime = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=tmp_path,
            preflight_mode="off",
            sdk_backend=backend,
        )
    )
    runtime.register(
        AgentSpec(
            base=CapabilitySpec(
                id="agent.responses_failed",
                kind=CapabilityKind.AGENT,
                name="ResponsesFailed",
                description="exercise failed terminal evidence",
            ),
            llm_config={"model": "gpt-responses"},
        )
    )

    result = await runtime.run("agent.responses_failed", input={"prompt": "x"})

    assert result.status.value == "failed"
    assert result.error_code == "PROVIDER_STREAM_TERMINAL"
    assert "provider failed" in str(result.error)
    assert "CAPRT_PROVIDER_STREAM_TERMINAL" not in str(result.error)
    assert "CAPRT_PROVIDER_STREAM_TERMINAL" not in str(result.output)
    assert result.node_report is not None
    assert result.node_report.status == "failed"
    assert result.node_report.reason == "model_error"
    assert result.node_report.completion_reason == "response_failed"
    assert result.node_report.usage is not None
    assert result.node_report.usage.model == "gpt-responses"
    assert result.node_report.usage.request_id == "resp_failed"
    assert result.node_report.usage.provider is None
    assert result.node_report.usage.provider_transport == "responses"
    assert result.node_report.meta["provider_terminal"]["request_id"] == "resp_failed"
    assert result.node_report.meta["provider_terminal"]["provider"] is None
    assert result.node_report.meta["provider_terminal"]["provider_transport"] == "responses"
    assert result.node_report.meta["provider_terminal"]["error_code"] == "PROVIDER_STREAM_TERMINAL"
    assert result.node_report.meta["provider_terminal"]["message"] == "model_error: provider failed (request_id=resp_failed)"
    assert result.node_report.meta["provider_terminal"]["status"] == "failed"


@pytest.mark.asyncio
async def test_runtime_responses_cancelled_terminal_preserves_incomplete_node_report(tmp_path) -> None:
    requester = _FakeResponsesRequester(
        [
            (
                "response.cancelled",
                '{"type":"response.cancelled","response":{"id":"resp_cancelled","status":"cancelled"}}',
            )
        ]
    )
    backend = _responses_backend(requester)
    runtime = Runtime(
        RuntimeConfig(mode="sdk_native", workspace_root=tmp_path, preflight_mode="off", sdk_backend=backend)
    )
    runtime.register(
        AgentSpec(
            base=CapabilitySpec(
                id="agent.responses_cancelled",
                kind=CapabilityKind.AGENT,
                name="ResponsesCancelled",
            ),
            llm_config={"model": "gpt-responses"},
        )
    )

    result = await runtime.run("agent.responses_cancelled", input={"prompt": "x"})

    assert result.status.value == "cancelled"
    assert result.error_code == "PROVIDER_STREAM_CANCELLED"
    assert result.error is None
    assert "CAPRT_PROVIDER_STREAM_TERMINAL" not in str(result.output)
    assert result.node_report is not None
    assert result.node_report.status == "incomplete"
    assert result.node_report.reason == "cancelled"
    assert result.node_report.completion_reason == "response_cancelled"
    assert result.node_report.usage is not None
    assert result.node_report.usage.request_id == "resp_cancelled"
    assert result.node_report.usage.model == "gpt-responses"
    assert result.node_report.usage.provider_transport == "responses"


@pytest.mark.asyncio
async def test_runtime_responses_incomplete_terminal_preserves_pending_node_report(tmp_path) -> None:
    requester = _FakeResponsesRequester(
        [
            (
                "response.incomplete",
                '{"type":"response.incomplete","response":{"id":"resp_incomplete","status":"incomplete"}}',
            )
        ]
    )
    backend = _responses_backend(requester)
    runtime = Runtime(
        RuntimeConfig(mode="sdk_native", workspace_root=tmp_path, preflight_mode="off", sdk_backend=backend)
    )
    runtime.register(
        AgentSpec(
            base=CapabilitySpec(
                id="agent.responses_incomplete",
                kind=CapabilityKind.AGENT,
                name="ResponsesIncomplete",
            ),
            llm_config={"model": "gpt-responses"},
        )
    )

    result = await runtime.run("agent.responses_incomplete", input={"prompt": "x"})

    assert result.status.value == "pending"
    assert result.error_code == "PROVIDER_STREAM_TERMINAL"
    assert result.error is None
    assert "CAPRT_PROVIDER_STREAM_TERMINAL" not in str(result.output)
    assert result.node_report is not None
    assert result.node_report.status == "incomplete"
    assert result.node_report.reason == "incomplete"
    assert result.node_report.completion_reason == "response_incomplete"
    assert result.node_report.usage is not None
    assert result.node_report.usage.request_id == "resp_incomplete"
    assert result.node_report.usage.model == "gpt-responses"
    assert result.node_report.usage.provider_transport == "responses"


@pytest.mark.asyncio
async def test_responses_bridge_normalizes_chat_style_named_tool_choice_dict() -> None:
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
                extra={"tool_choice": {"type": "function", "function": {"name": "lookup"}}},
            )
        )
    ]

    assert requester.last_request_data is not None
    assert requester.last_request_data.request_options["tool_choice"] == {"type": "function", "name": "lookup"}


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
async def test_responses_bridge_preserves_chat_style_image_url_content_parts() -> None:
    """Responses bridge 不能把 chat.completions 多模态 image_url 降级为空文本。"""

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
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "inspect this"},
                            {"type": "image_url", "image_url": {"url": "https://example.test/a.png", "detail": "high"}},
                            {"type": "image_url", "image_url": "data:image/png;base64,abc"},
                        ],
                    }
                ],
                tools=[],
            )
        )
    ]

    assert requester.last_request_data is not None
    assert requester.last_request_data.data["input"] == [
        {
            "type": "message",
            "role": "user",
            "content": [
                {"type": "input_text", "text": "inspect this"},
                {"type": "input_image", "image_url": "https://example.test/a.png", "detail": "high"},
                {"type": "input_image", "image_url": "data:image/png;base64,abc"},
            ],
        }
    ]


@pytest.mark.asyncio
async def test_responses_bridge_forwards_tool_choice_from_llm_config_extra() -> None:
    """
    Responses 真实 provider 路径需要支持 tool_choice opt-in。

    AgentSpec.llm_config 会通过 request.extra["tool_choice"] 到达 backend；
    Responses bridge 必须把该字段写入 request_options，否则真实 provider
    tool_call + approval 集成只能靠模型自发选择工具，生产回归不稳定。
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
                extra={"tool_choice": "required"},
            )
        )
    ]

    assert requester.last_request_data is not None
    assert requester.last_request_data.request_options["tool_choice"] == "required"


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


@pytest.mark.asyncio
async def test_responses_bridge_preserves_assistant_content_before_tool_calls() -> None:
    """assistant 同 turn 同时有 content/tool_calls 时，Responses input 不能反转文本与工具调用顺序。"""

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
                        "content": "I will call lookup.",
                        "tool_calls": [
                            {
                                "id": "call_lookup",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": '{"query":"caprt"}'},
                            }
                        ],
                    },
                ],
                tools=[],
            )
        )
    ]

    assert requester.last_request_data is not None
    assert requester.last_request_data.data["input"][1:] == [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "input_text", "text": "I will call lookup."}],
        },
        {
            "type": "function_call",
            "call_id": "call_lookup",
            "name": "lookup",
            "arguments": '{"query":"caprt"}',
        },
    ]


@pytest.mark.asyncio
async def test_responses_bridge_stream_end_without_terminal_fails_closed() -> None:
    """Responses 流没有明确 terminal event 时不能 synthetic success。"""

    requester = _FakeResponsesRequester(
        [
            (
                "response.output_text.delta",
                '{"type":"response.output_text.delta","delta":"partial"}',
            )
        ]
    )
    backend = _responses_backend(requester)

    with pytest.raises(ProviderStreamTerminalError, match="ended without response terminal event"):
        _ = [
            ev
            async for ev in backend.stream_chat(
                ChatRequest(model="gpt-responses", messages=[{"role": "user", "content": "x"}], tools=[])
            )
        ]


@pytest.mark.asyncio
async def test_responses_bridge_falls_back_to_non_stream_when_provider_stream_is_empty() -> None:
    """真实 provider 可能支持 /responses 但不产出 streaming terminal；此时应降级到 non-stream。"""

    usage_events = []
    requester = _FakeResponsesRequesterWithNonStreamFallback()
    backend = _responses_backend(requester)  # type: ignore[arg-type]

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

    assert requester.stream_values == [True, False]
    assert [ev.type for ev in out] == ["text_delta", "tool_calls", "completed"]
    assert out[0].text == "fallback ok"
    assert out[1].tool_calls is not None
    assert out[1].tool_calls[0].call_id == "call_fallback"
    assert out[1].tool_calls[0].name == "lookup"
    assert out[1].tool_calls[0].args == {"query": "fallback"}
    assert out[2].request_id == "resp_fallback"
    assert out[2].provider is None
    assert usage_events == [
        {
            "model": "gpt-responses",
            "input_tokens": 2,
            "output_tokens": 3,
            "total_tokens": 5,
            "request_id": "resp_fallback",
            "provider": None,
            "provider_transport": "responses",
        }
    ]


@pytest.mark.asyncio
async def test_responses_bridge_empty_stream_fallback_uses_fresh_requester_and_request_data() -> None:
    """空流 fallback 是第二次独立请求，不能复用半失败 requester/request_data。"""

    factory = _FakeResponsesRequesterFactoryForFallbackIsolation()
    backend = _responses_backend_from_factory(factory)

    out = [
        ev
        async for ev in backend.stream_chat(
            ChatRequest(model="gpt-responses", messages=[{"role": "user", "content": "x"}], tools=[])
        )
    ]

    assert [ev.type for ev in out] == ["text_delta", "tool_calls", "completed"]
    assert len(factory.requesters) == 2
    assert factory.requesters[0].stream_values == [True]
    assert factory.requesters[1].stream_values == [False]


@pytest.mark.asyncio
async def test_responses_bridge_falls_back_when_requester_raises_empty_stream_error() -> None:
    """Agently requester 可能直接 raise 空流错误，而不是 yield error event。"""

    requester = _FakeResponsesRequesterRaisesBeforeNonStreamFallback()
    backend = _responses_backend(requester)  # type: ignore[arg-type]

    out = [
        ev
        async for ev in backend.stream_chat(
            ChatRequest(model="gpt-responses", messages=[{"role": "user", "content": "x"}], tools=[])
        )
    ]

    assert requester.stream_values == [True, False]
    assert [ev.type for ev in out] == ["text_delta", "completed"]
    assert out[0].text == "fallback ok"
    assert out[-1].request_id == "resp_fallback_raise"


@pytest.mark.asyncio
async def test_responses_bridge_does_not_fallback_when_provider_error_only_mentions_stop_async_iteration() -> None:
    """普通 provider 错误即使提到 StopAsyncIteration，也必须 fail-closed。"""

    requester = _FakeResponsesRequesterRaisesProviderErrorMentioningStopAsyncIteration()
    backend = _responses_backend(requester)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="provider auth failure"):
        _ = [
            ev
            async for ev in backend.stream_chat(
                ChatRequest(model="gpt-responses", messages=[{"role": "user", "content": "x"}], tools=[])
            )
        ]

    assert requester.stream_values == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("partial_kind", ["text", "tool"])
async def test_responses_bridge_does_not_fallback_after_partial_stream_events(partial_kind: str) -> None:
    """stream 已向下游发出内容后，StopAsyncIteration 不能降级成 non-stream success。"""

    requester = _FakeResponsesRequesterPartialThenFallback(partial_kind=partial_kind)
    backend = _responses_backend(requester)  # type: ignore[arg-type]

    with pytest.raises(ProviderStreamTerminalError, match="partial Responses stream"):
        _ = [
            ev
            async for ev in backend.stream_chat(
                ChatRequest(model="gpt-responses", messages=[{"role": "user", "content": "x"}], tools=[])
            )
        ]
    assert requester.stream_values == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected_status", "expected_reason"),
    [
        ("failed", "failed", "bad_status"),
        ("incomplete", "incomplete", "bad_status"),
        ("cancelled", "incomplete", "cancelled"),
    ],
)
async def test_responses_fallback_fails_closed_for_non_completed_status(
    status: str, expected_status: str, expected_reason: str
) -> None:
    """Non-stream fallback 只有 status=completed 才能产出成功 completed event。"""

    requester = _FakeResponsesRequesterFallbackStatus(status)
    backend = _responses_backend(requester)  # type: ignore[arg-type]

    with pytest.raises(ProviderStreamTerminalError) as exc_info:
        _ = [
            ev
            async for ev in backend.stream_chat(
                ChatRequest(model="gpt-responses", messages=[{"role": "user", "content": "x"}], tools=[])
            )
        ]

    assert requester.stream_values == [True, False]
    assert exc_info.value.status == expected_status
    assert exc_info.value.reason == expected_reason


def test_openai_provider_requester_factory_keeps_transport_settings_isolated() -> None:
    """公开 OpenAI-compatible helper 不能用全局 settings 导致后建 factory 污染先建 factory。"""

    first = build_openai_provider_requester_factory(
        base_url="https://first.example/v1",
        transport_model="model-first",
        api_key="key-first",
        strategy="chat_completions",
    )
    second = build_openai_provider_requester_factory(
        base_url="https://second.example/v1",
        transport_model="model-second",
        api_key="key-second",
        strategy="chat_completions",
    )

    first_data = first().generate_request_data()
    second_data = second().generate_request_data()
    first_again_data = first().generate_request_data()

    assert first_data.request_url == "https://first.example/v1/chat/completions"
    assert first_data.request_options["model"] == "model-first"
    assert second_data.request_url == "https://second.example/v1/chat/completions"
    assert second_data.request_options["model"] == "model-second"
    assert first_again_data.request_url == "https://first.example/v1/chat/completions"
    assert first_again_data.request_options["model"] == "model-first"


def test_openai_provider_requester_factory_rejects_http_without_explicit_allow() -> None:
    """公开 helper 默认不能把 API key 发往明文 HTTP transport。"""

    with pytest.raises(ValueError, match="https|insecure"):
        build_openai_provider_requester_factory(
            base_url="http://provider.internal/v1",
            transport_model="model-live",
            api_key="test-key",
            strategy="chat_completions",
        )


def test_openai_provider_requester_factory_allows_http_only_with_explicit_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """私有 HTTP provider 必须显式声明受控例外。"""

    monkeypatch.setenv("CAPRT_REAL_PROVIDER_ALLOW_INSECURE_TRANSPORT", "1")
    factory = build_openai_provider_requester_factory(
        base_url="http://provider.internal/v1",
        transport_model="model-live",
        api_key="test-key",
        strategy="chat_completions",
    )

    assert factory.requester_strategy == "chat_completions"


def test_openai_provider_requester_factory_allows_http_with_explicit_parameter(monkeypatch: pytest.MonkeyPatch) -> None:
    """公开 helper 参数应能表达私有 HTTP provider 例外，避免只依赖隐藏 env。"""

    monkeypatch.delenv("CAPRT_REAL_PROVIDER_ALLOW_INSECURE_TRANSPORT", raising=False)
    factory = build_openai_provider_requester_factory(
        base_url="http://provider.internal/v1",
        transport_model="model-live",
        api_key="test-key",
        strategy="chat_completions",
        allow_insecure_transport=True,
    )

    assert factory.requester_strategy == "chat_completions"


def test_openai_provider_requester_factory_rejects_untrusted_host_when_allowlist_is_supplied() -> None:
    """公开 helper 支持生产调用方显式限制 trusted provider host。"""

    with pytest.raises(ValueError, match="trusted host|allowed_hosts"):
        build_openai_provider_requester_factory(
            base_url="https://evil.example/v1",
            transport_model="model-live",
            api_key="test-key",
            strategy="chat_completions",
            allowed_hosts={"provider.example"},
        )


def test_openai_provider_requester_factory_accepts_trusted_host_when_allowlist_is_supplied() -> None:
    factory = build_openai_provider_requester_factory(
        base_url="https://provider.example/v1",
        transport_model="model-live",
        api_key="test-key",
        strategy="chat_completions",
        allowed_hosts={"provider.example"},
    )

    assert factory.requester_strategy == "chat_completions"
