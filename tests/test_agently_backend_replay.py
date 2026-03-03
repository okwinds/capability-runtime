import pytest

from capability_runtime.adapters.agently_backend import AgentlyBackendConfig, AgentlyChatBackend
from skills_runtime.llm.protocol import ChatRequest
from skills_runtime.tools.protocol import ToolSpec


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
async def test_backend_filters_non_jsonable_extra_fields_before_requester_serialization():
    """
    回归护栏：
    - skills_runtime 可能把 on_retry=function 等回调塞进 ChatRequest.extra；
    - 这类值不属于 wire payload，若透传会导致 requester JSON 序列化失败；
    - backend 必须过滤掉不可 JSON 序列化字段，同时保留可序列化字段。
    """

    captured = {}

    class _CapturingRequester(_FakeRequester):
        async def request_model(self, request_data):
            captured["options"] = dict(getattr(request_data, "request_options", {}) or {})
            async for x in super().request_model(request_data):
                yield x

    def factory():
        return _CapturingRequester([("message", "[DONE]")])

    backend = AgentlyChatBackend(config=AgentlyBackendConfig(requester_factory=factory))

    out = [ev async for ev in backend.stream_chat(
        ChatRequest(
            model="m",
            messages=[{"role": "user", "content": "x"}],
            tools=[],
            extra={
                "seed": 1,
                "on_retry": lambda *_a, **_k: None,
                "bad": {"nested": (lambda: 1)},
            },
        )
    )]

    assert out and out[-1].type == "completed"
    opts = captured.get("options") or {}
    assert opts.get("seed") == 1
    assert "on_retry" not in opts
    assert "bad" not in opts


@pytest.mark.asyncio
async def test_backend_tool_choice_extra_overrides_preset_request_options():
    """
    回归护栏：
    - 某些 requester/backend 可能在 request_options 中预置 tool_choice（例如默认 "auto"）；
    - per-run llm_config 会写入 ChatRequest.extra["tool_choice"]；
    - adapter 层必须确保 extra.tool_choice 优先级更高，最终发送给 provider 的 tool_choice 必须等于覆写值。
    """

    captured = {}

    class _PresetToolChoiceRequestData(_FakeRequestData):
        def __init__(self) -> None:
            super().__init__()
            self.request_options = {"tool_choice": "auto"}

    class _CapturingRequester(_FakeRequester):
        def generate_request_data(self):
            return _PresetToolChoiceRequestData()

        async def request_model(self, request_data):
            captured["options"] = dict(getattr(request_data, "request_options", {}) or {})
            async for x in super().request_model(request_data):
                yield x

    def factory():
        return _CapturingRequester([("message", "[DONE]")])

    backend = AgentlyChatBackend(config=AgentlyBackendConfig(requester_factory=factory))

    tool_choice = {"type": "function", "function": {"name": "file_write"}}
    tool_spec_write = ToolSpec(
        name="file_write",
        description="write file",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
        requires_approval=False,
    )
    tool_spec_exec = ToolSpec(
        name="shell_exec",
        description="exec shell",
        parameters={
            "type": "object",
            "properties": {"argv": {"type": "array", "items": {"type": "string"}}},
            "required": ["argv"],
        },
        requires_approval=False,
    )

    out = [
        ev
        async for ev in backend.stream_chat(
            ChatRequest(
                model="m",
                messages=[{"role": "user", "content": "x"}],
                tools=[tool_spec_write, tool_spec_exec],
                extra={"tool_choice": tool_choice},
            )
        )
    ]
    assert out and out[-1].type == "completed"

    opts = captured.get("options") or {}
    # 兼容性：OpenAI 新格式 tool_choice dict 不应直接透传到 wire；
    # 对于不支持 tool_choice.function 的 OpenAICompatible server，归一化为 tool_choice="required"。
    assert opts.get("tool_choice") == "required"
    tools = opts.get("tools") or []
    assert isinstance(tools, list)
    assert len(tools) == 1
    assert tools[0]["function"]["name"] == "file_write"


@pytest.mark.asyncio
async def test_backend_tool_choice_string_is_passthrough_and_tools_not_filtered():
    captured = {}

    class _PresetToolChoiceRequestData(_FakeRequestData):
        def __init__(self) -> None:
            super().__init__()
            self.request_options = {"tool_choice": "auto"}

    class _CapturingRequester(_FakeRequester):
        def generate_request_data(self):
            return _PresetToolChoiceRequestData()

        async def request_model(self, request_data):
            captured["options"] = dict(getattr(request_data, "request_options", {}) or {})
            async for x in super().request_model(request_data):
                yield x

    def factory():
        return _CapturingRequester([("message", "[DONE]")])

    backend = AgentlyChatBackend(config=AgentlyBackendConfig(requester_factory=factory))

    tool_spec_write = ToolSpec(
        name="file_write",
        description="write file",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
        requires_approval=False,
    )
    tool_spec_exec = ToolSpec(
        name="shell_exec",
        description="exec shell",
        parameters={
            "type": "object",
            "properties": {"argv": {"type": "array", "items": {"type": "string"}}},
            "required": ["argv"],
        },
        requires_approval=False,
    )

    out = [
        ev
        async for ev in backend.stream_chat(
            ChatRequest(
                model="m",
                messages=[{"role": "user", "content": "x"}],
                tools=[tool_spec_write, tool_spec_exec],
                extra={"tool_choice": "required"},
            )
        )
    ]
    assert out and out[-1].type == "completed"

    opts = captured.get("options") or {}
    assert opts.get("tool_choice") == "required"
    tools = opts.get("tools") or []
    assert isinstance(tools, list)
    assert {t["function"]["name"] for t in tools} == {"file_write", "shell_exec"}


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
async def test_backend_defers_completed_until_after_tool_calls_when_done_flushes_tool_calls():
    """
    回归护栏（真实 provider 兼容）：
    - 某些 OpenAICompatible server 会在 tool_calls delta 之后，先发一个 finish_reason="stop" 的 chunk；
    - SDK parser 可能先产出 completed，再在 [DONE] 时 flush tool_calls；
    - 若上游 agent loop 在 completed 后停止消费，会丢失 tool_calls，最终表现为 NodeReport.tool_calls 为空；
    - adapter 层必须保证：只要存在 tool_calls，tool_calls 事件必须先于 completed 被 yield。
    """

    backend = _backend_from_items(
        [
            (
                "message",
                '{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"shell_exec","arguments":"{\\"argv\\":[\\"echo\\",\\"hi\\"]}"}}]},"finish_reason":null}]}',
            ),
            ("message", '{"choices":[{"delta":{},"finish_reason":"stop"}]}'),
            ("message", "[DONE]"),
        ]
    )

    out = [
        ev
        async for ev in backend.stream_chat(
            ChatRequest(model="m", messages=[{"role": "user", "content": "x"}], tools=[])
        )
    ]

    types = [e.type for e in out]
    assert types.count("tool_calls") == 1
    assert types.count("completed") == 1
    assert types.index("tool_calls") < types.index("completed")

    tool_events = [e for e in out if e.type == "tool_calls"]
    calls = tool_events[0].tool_calls or []
    assert len(calls) == 1
    assert calls[0].call_id == "call_1"
    assert calls[0].name == "shell_exec"
    assert calls[0].args["argv"] == ["echo", "hi"]


@pytest.mark.asyncio
async def test_backend_defers_completed_until_after_tool_calls_when_stop_then_done_flushes_tool_calls():
    """
    回归护栏（更贴近真实 provider）：
    - tool_calls 参数可能跨多个 delta 拼接；
    - 某些 OpenAICompatible server 可能先发 finish_reason="stop" 的 chunk；
    - 直到 [DONE] 才触发 parser flush tool_calls；
    - adapter 必须保证 tool_calls 先于 completed 被 yield。
    """

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
            ("message", '{"choices":[{"delta":{},"finish_reason":"stop"}]}'),
            ("message", "[DONE]"),
        ]
    )

    out = [
        ev
        async for ev in backend.stream_chat(
            ChatRequest(model="m", messages=[{"role": "user", "content": "x"}], tools=[])
        )
    ]

    types = [e.type for e in out]
    assert types.count("tool_calls") == 1
    assert types.count("completed") == 1
    assert types.index("tool_calls") < types.index("completed")

    tool_events = [e for e in out if e.type == "tool_calls"]
    calls = tool_events[0].tool_calls or []
    assert len(calls) == 1
    assert calls[0].call_id == "call_1"
    assert calls[0].name == "shell_exec"
    assert calls[0].args["argv"] == ["echo", "hi"]


@pytest.mark.asyncio
async def test_backend_buffers_completed_until_after_tool_calls_when_parser_order_is_completed_then_tool_calls(monkeypatch):
    """
    回归护栏（上游漂移/奇异顺序）：
    - 模拟 parser 先 emit completed，再在后续 chunk（例如 [DONE]）flush tool_calls；
    - adapter 必须缓冲 completed，确保对外顺序为 tool_calls -> completed。
    """

    from skills_runtime.llm.chat_sse import ChatStreamEvent
    from skills_runtime.tools.protocol import ToolCall

    class _WeirdOrderParser:
        def feed_data(self, data: str):
            if '"finish_reason":"stop"' in data:
                return [ChatStreamEvent(type="completed", finish_reason="stop")]
            if data.strip() in ("[DONE]", "DONE"):
                # 更“坏”的实现：feed_data 看到 [DONE] 不 flush，必须靠 finish() 才能拿到 tool_calls。
                return []
            return []

        def finish(self):
            return [
                ChatStreamEvent(
                    type="tool_calls",
                    tool_calls=[ToolCall(call_id="call_1", name="file_write", args={"path": "a.py", "content": "x"})],
                )
            ]

    import capability_runtime.adapters.agently_backend as module

    monkeypatch.setattr(module, "ChatCompletionsSseParser", _WeirdOrderParser)

    backend = _backend_from_items(
        [
            ("message", '{"choices":[{"delta":{},"finish_reason":"stop"}]}'),
            ("message", "[DONE]"),
        ]
    )

    out = [
        ev
        async for ev in backend.stream_chat(
            ChatRequest(model="m", messages=[{"role": "user", "content": "x"}], tools=[])
        )
    ]
    types = [e.type for e in out]
    assert types.count("tool_calls") == 1
    assert types.count("completed") == 1
    assert types.index("tool_calls") < types.index("completed")


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
