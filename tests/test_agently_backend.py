import pytest

from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec, Runtime, RuntimeConfig
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
        self.last_request_data = None

    def generate_request_data(self):
        return _FakeRequestData()

    async def request_model(self, request_data):
        self.last_request_data = request_data
        for item in self._items:
            yield item


class _FakeRequesterFactory:
    def __init__(self, item_batches):
        self._item_batches = list(item_batches)
        self.instances = []

    def __call__(self):
        index = len(self.instances)
        items = self._item_batches[index]
        requester = _FakeRequester(items)
        self.instances.append(requester)
        return requester


class _RaiseOnRequestRequester(_FakeRequester):
    def __init__(self, error):
        super().__init__([])
        self._error = error

    async def request_model(self, request_data):
        self.last_request_data = request_data
        raise self._error


class _MixedRequesterFactory:
    def __init__(self, requesters):
        self._requesters = list(requesters)
        self.instances = []

    def __call__(self):
        requester = self._requesters[len(self.instances)]
        self.instances.append(requester)
        return requester


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
                '{"id":"req_123","provider":"openai-compatible","choices":[{"delta":{},"finish_reason":"stop"}],"model":"bridge-usage-model","usage":{"prompt_tokens":11,"completion_tokens":7,"total_tokens":18}}',
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
            "request_id": "req_123",
            "provider": "openai-compatible",
        }
    ]


@pytest.mark.asyncio
async def test_agently_backend_usage_sink_accepts_missing_request_metadata():
    usage_events = []
    backend = _backend_from_items(
        [
            (
                "message",
                '{"choices":[{"delta":{},"finish_reason":"stop"}],"model":"bridge-usage-model","usage":{"prompt_tokens":1,"completion_tokens":2,"total_tokens":3}}',
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

    assert [e.type for e in out] == ["completed"]
    assert usage_events == [
        {
            "model": "bridge-usage-model",
            "input_tokens": 1,
            "output_tokens": 2,
            "total_tokens": 3,
            "request_id": None,
            "provider": None,
        }
    ]


@pytest.mark.asyncio
async def test_agently_sse_usage_request_metadata_reaches_runtime_node_report(tmp_path):
    backend = _backend_from_items(
        [
            ("message", '{"choices":[{"delta":{"content":"ok"},"finish_reason":null}]}'),
            (
                "message",
                '{"id":"req_123","choices":[{"delta":{},"finish_reason":"stop"}],"model":"bridge-usage-model","usage":{"prompt_tokens":11,"completion_tokens":7,"total_tokens":18}}',
            ),
            ("message", "[DONE]"),
        ]
    )
    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=tmp_path,
            sdk_config_paths=[],
            preflight_mode="off",
            sdk_backend=backend,
        )
    )
    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="agent.sse_usage_metadata",
                kind=CapabilityKind.AGENT,
                name="SSEUsageMetadata",
                description="离线：SSE completed usage metadata 透传。",
            ),
        )
    )

    result = await rt.run("agent.sse_usage_metadata", input={"prompt": "x"})

    assert result.node_report is not None
    assert result.node_report.usage is not None
    assert result.node_report.usage.input_tokens == 11
    assert result.node_report.usage.output_tokens == 7
    assert result.node_report.usage.total_tokens == 18
    assert result.node_report.usage.request_id == "req_123"
    assert result.node_report.usage.provider == "openai"


@pytest.mark.asyncio
async def test_agently_backend_requests_include_usage_by_default_and_preserves_existing_stream_options():
    requester = _FakeRequester(
        [
            ("message", '{"choices":[{"delta":{},"finish_reason":"stop"}]}'),
            ("message", "[DONE]"),
        ]
    )
    backend = AgentlyChatBackend(config=AgentlyBackendConfig(requester_factory=lambda: requester))

    out = [
        ev
        async for ev in backend.stream_chat(
            ChatRequest(
                model="m",
                messages=[{"role": "user", "content": "x"}],
                tools=[],
                extra={"stream_options": {"existing_flag": "keep"}},
            )
        )
    ]

    assert [e.type for e in out] == ["completed"]
    assert requester.last_request_data is not None
    assert requester.last_request_data.request_options["stream_options"] == {
        "existing_flag": "keep",
        "include_usage": True,
    }


@pytest.mark.asyncio
async def test_agently_backend_retries_without_stream_options_when_provider_rejects_include_usage():
    factory = _FakeRequesterFactory(
        [
            [
                ("error", RuntimeError("400 Bad Request: Unknown parameter: 'stream_options.include_usage'")),
            ],
            [
                ("message", '{"choices":[{"delta":{},"finish_reason":"stop"}]}'),
                ("message", "[DONE]"),
            ],
        ]
    )
    backend = AgentlyChatBackend(config=AgentlyBackendConfig(requester_factory=factory))

    out = [
        ev
        async for ev in backend.stream_chat(
            ChatRequest(
                model="m",
                messages=[{"role": "user", "content": "x"}],
                tools=[],
            )
        )
    ]

    assert [e.type for e in out] == ["completed"]
    assert len(factory.instances) == 2
    assert factory.instances[0].last_request_data.request_options["stream_options"] == {"include_usage": True}
    assert "stream_options" not in factory.instances[1].last_request_data.request_options


@pytest.mark.asyncio
async def test_agently_backend_retries_without_stream_options_when_requester_raises() -> None:
    error = RuntimeError("400 Bad Request: Unknown parameter: 'stream_options.include_usage'")
    factory = _MixedRequesterFactory(
        [
            _RaiseOnRequestRequester(error),
            _FakeRequester(
                [
                    ("message", '{"choices":[{"delta":{},"finish_reason":"stop"}]}'),
                    ("message", "[DONE]"),
                ]
            ),
        ]
    )
    backend = AgentlyChatBackend(config=AgentlyBackendConfig(requester_factory=factory))

    out = [
        ev
        async for ev in backend.stream_chat(
            ChatRequest(
                model="m",
                messages=[{"role": "user", "content": "x"}],
                tools=[],
            )
        )
    ]

    assert [e.type for e in out] == ["completed"]
    assert len(factory.instances) == 2
    assert factory.instances[0].last_request_data.request_options["stream_options"] == {"include_usage": True}
    assert "stream_options" not in factory.instances[1].last_request_data.request_options
