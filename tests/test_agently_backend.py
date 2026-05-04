import pytest

from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec, Runtime, RuntimeConfig
from capability_runtime.adapters.agently_backend import AgentlyBackendConfig, AgentlyChatBackend
from capability_runtime.sdk_lifecycle import _merge_supplemental_usage_metadata_event
from skills_runtime.core.contracts import AgentEvent
from skills_runtime.llm.chat_sse import ChatStreamEvent
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


class _UpstreamUsageWithSinkBackend:
    """测试用 backend：同时产出上游 usage 与 `_caprt_usage_sink` supplemental payload。"""

    def __init__(
        self,
        *,
        completed_usage,
        sink_payload=None,
        sink_payloads=None,
        completed_request_id=None,
        completed_provider=None,
    ):
        """保存一次 runtime 调用需要返回的上游 usage 与 sink payload。"""

        if sink_payloads is None:
            sink_payloads = [sink_payload]
        self._sink_payloads = [dict(item) for item in sink_payloads if isinstance(item, dict)]
        self._completed_usage = completed_usage
        self._completed_request_id = completed_request_id
        self._completed_provider = completed_provider

    async def stream_chat(self, request):
        """先调用 usage sink，再返回会触发上游 `llm_usage` 的 completed 事件。"""

        sink = None
        if isinstance(getattr(request, "extra", None), dict):
            candidate = request.extra.get("_caprt_usage_sink")
            if callable(candidate):
                sink = candidate
        if sink is not None:
            for payload in self._sink_payloads:
                sink(dict(payload))
        yield ChatStreamEvent(type="text_delta", text="ok")
        yield ChatStreamEvent(
            type="completed",
            finish_reason="stop",
            usage=dict(self._completed_usage),
            request_id=self._completed_request_id,
            provider=self._completed_provider,
        )


def _backend_from_items(items):
    def factory():
        return _FakeRequester(items)

    return AgentlyChatBackend(config=AgentlyBackendConfig(requester_factory=factory))


async def _run_usage_backend(backend, tmp_path):
    """用 sdk_native Runtime 运行测试 backend，并返回 CapabilityResult。"""

    rt = _make_usage_runtime(backend, tmp_path)
    return await rt.run("agent.upstream_usage_with_sink", input={"prompt": "x"})


def _make_usage_runtime(backend, tmp_path):
    """构造注册了 usage 测试 Agent 的 sdk_native Runtime。"""

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
                id="agent.upstream_usage_with_sink",
                kind=CapabilityKind.AGENT,
                name="UpstreamUsageWithSink",
                description="离线：上游 llm_usage 与 usage sink metadata 合并。",
            ),
        )
    )
    return rt


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
async def test_upstream_llm_usage_merges_sink_request_metadata_without_double_counting_tokens(tmp_path):
    backend = _UpstreamUsageWithSinkBackend(
        sink_payload={
            "model": "sink-model",
            "input_tokens": 99,
            "output_tokens": 99,
            "total_tokens": 198,
            "request_id": "req_sink_123",
            "provider": "gateway-provider",
        },
        completed_usage={"input_tokens": 5, "output_tokens": 6, "total_tokens": 11},
    )

    result = await _run_usage_backend(backend, tmp_path)

    assert result.node_report is not None
    assert result.node_report.usage is not None
    assert result.node_report.usage.input_tokens == 5
    assert result.node_report.usage.output_tokens == 6
    assert result.node_report.usage.total_tokens == 11
    assert result.node_report.usage.request_id == "req_sink_123"
    assert result.node_report.usage.provider == "gateway-provider"


@pytest.mark.asyncio
async def test_upstream_llm_usage_merges_multiple_sink_payloads_as_one_metadata_patch(tmp_path):
    backend = _UpstreamUsageWithSinkBackend(
        sink_payloads=[
            {"input_tokens": 99, "output_tokens": 99, "total_tokens": 198},
            {"request_id": "req_sink_late", "provider": "gateway-provider-late"},
        ],
        completed_usage={"input_tokens": 3, "output_tokens": 4, "total_tokens": 7},
    )

    result = await _run_usage_backend(backend, tmp_path)

    assert result.node_report is not None
    assert result.node_report.usage is not None
    assert result.node_report.usage.input_tokens == 3
    assert result.node_report.usage.output_tokens == 4
    assert result.node_report.usage.total_tokens == 7
    assert result.node_report.usage.request_id == "req_sink_late"
    assert result.node_report.usage.provider == "gateway-provider-late"


@pytest.mark.asyncio
async def test_upstream_llm_usage_metadata_is_not_overwritten_by_sink_payload(tmp_path):
    backend = _UpstreamUsageWithSinkBackend(
        sink_payload={
            "model": "sink-model",
            "input_tokens": 99,
            "output_tokens": 99,
            "total_tokens": 198,
            "request_id": "req_sink_456",
            "provider": "sink-provider",
        },
        completed_usage={"input_tokens": 7, "output_tokens": 8, "total_tokens": 15},
        completed_request_id="req_upstream_456",
        completed_provider="upstream-provider",
    )

    result = await _run_usage_backend(backend, tmp_path)

    assert result.node_report is not None
    assert result.node_report.usage is not None
    assert result.node_report.usage.input_tokens == 7
    assert result.node_report.usage.output_tokens == 8
    assert result.node_report.usage.total_tokens == 15
    assert result.node_report.usage.request_id == "req_upstream_456"
    assert result.node_report.usage.provider == "upstream-provider"


def test_supplemental_usage_metadata_helper_can_fill_missing_model() -> None:
    ev = AgentEvent(
        type="llm_usage",
        timestamp="2026-05-04T00:00:00Z",
        run_id="run_1",
        payload={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
    )

    merged = _merge_supplemental_usage_metadata_event(
        ev=ev,
        supplemental_payloads=[{"model": "sink-model", "request_id": "req_model", "provider": "sink-provider"}],
    )

    assert merged.payload == {
        "input_tokens": 1,
        "output_tokens": 2,
        "total_tokens": 3,
        "model": "sink-model",
        "request_id": "req_model",
        "provider": "sink-provider",
    }


def test_supplemental_usage_metadata_helper_does_not_overwrite_existing_model() -> None:
    ev = AgentEvent(
        type="llm_usage",
        timestamp="2026-05-04T00:00:00Z",
        run_id="run_1",
        payload={
            "model": "upstream-model",
            "input_tokens": 1,
            "output_tokens": 2,
            "total_tokens": 3,
        },
    )

    merged = _merge_supplemental_usage_metadata_event(
        ev=ev,
        supplemental_payloads=[{"model": "sink-model", "request_id": "req_model", "provider": "sink-provider"}],
    )

    assert merged.payload == {
        "model": "upstream-model",
        "input_tokens": 1,
        "output_tokens": 2,
        "total_tokens": 3,
        "request_id": "req_model",
        "provider": "sink-provider",
    }


@pytest.mark.parametrize("placeholder_provider", ["openai", "openai-compatible"])
def test_supplemental_usage_metadata_helper_overwrites_placeholder_provider(placeholder_provider: str) -> None:
    ev = AgentEvent(
        type="llm_usage",
        timestamp="2026-05-05T00:00:00Z",
        run_id="run_1",
        payload={
            "model": "upstream-model",
            "input_tokens": 5,
            "output_tokens": 6,
            "total_tokens": 11,
            "request_id": "req_upstream",
            "provider": placeholder_provider,
        },
    )

    merged = _merge_supplemental_usage_metadata_event(
        ev=ev,
        supplemental_payloads=[
            {
                "model": "sink-model",
                "input_tokens": 99,
                "output_tokens": 99,
                "total_tokens": 198,
                "request_id": "req_sink",
                "provider": "gateway-provider",
            }
        ],
    )

    assert merged.payload == {
        "model": "upstream-model",
        "input_tokens": 5,
        "output_tokens": 6,
        "total_tokens": 11,
        "request_id": "req_upstream",
        "provider": "gateway-provider",
        "provider_upstream": placeholder_provider,
    }


@pytest.mark.parametrize("sink_provider", ["", "   ", "openai", "openai-compatible"])
def test_supplemental_usage_metadata_helper_keeps_placeholder_when_sink_is_not_effective(
    sink_provider: str,
) -> None:
    ev = AgentEvent(
        type="llm_usage",
        timestamp="2026-05-05T00:00:00Z",
        run_id="run_1",
        payload={
            "input_tokens": 5,
            "output_tokens": 6,
            "total_tokens": 11,
            "provider": "openai",
        },
    )

    merged = _merge_supplemental_usage_metadata_event(
        ev=ev,
        supplemental_payloads=[{"provider": sink_provider}],
    )

    assert merged.payload == {
        "input_tokens": 5,
        "output_tokens": 6,
        "total_tokens": 11,
        "provider": "openai",
    }


@pytest.mark.parametrize("placeholder_provider", ["openai", "openai-compatible"])
@pytest.mark.asyncio
async def test_upstream_placeholder_provider_is_replaced_by_sink_effective_provider(
    tmp_path,
    placeholder_provider: str,
):
    backend = _UpstreamUsageWithSinkBackend(
        sink_payload={
            "input_tokens": 99,
            "output_tokens": 99,
            "total_tokens": 198,
            "request_id": "req_sink_gateway",
            "provider": "gateway-provider",
        },
        completed_usage={"input_tokens": 5, "output_tokens": 6, "total_tokens": 11},
        completed_request_id="req_gateway",
        completed_provider=placeholder_provider,
    )
    rt = _make_usage_runtime(backend, tmp_path)

    items = [
        item
        async for item in rt.run_stream("agent.upstream_usage_with_sink", input={"prompt": "x"})
    ]
    usage_events = [item for item in items if isinstance(item, AgentEvent) and item.type == "llm_usage"]
    result = items[-1]

    assert usage_events
    assert usage_events[-1].payload["provider"] == "gateway-provider"
    assert usage_events[-1].payload["provider_upstream"] == placeholder_provider
    assert result.node_report is not None
    assert result.node_report.usage is not None
    assert result.node_report.usage.input_tokens == 5
    assert result.node_report.usage.output_tokens == 6
    assert result.node_report.usage.total_tokens == 11
    assert result.node_report.usage.request_id == "req_gateway"
    assert result.node_report.usage.provider == "gateway-provider"


@pytest.mark.asyncio
async def test_upstream_placeholder_provider_keeps_placeholder_when_sink_is_placeholder(tmp_path):
    backend = _UpstreamUsageWithSinkBackend(
        sink_payload={
            "input_tokens": 99,
            "output_tokens": 99,
            "total_tokens": 198,
            "request_id": "req_sink_gateway",
            "provider": "openai-compatible",
        },
        completed_usage={"input_tokens": 5, "output_tokens": 6, "total_tokens": 11},
        completed_request_id="req_gateway",
        completed_provider="openai",
    )
    rt = _make_usage_runtime(backend, tmp_path)

    items = [
        item
        async for item in rt.run_stream("agent.upstream_usage_with_sink", input={"prompt": "x"})
    ]
    usage_events = [item for item in items if isinstance(item, AgentEvent) and item.type == "llm_usage"]
    result = items[-1]

    assert usage_events
    assert usage_events[-1].payload["provider"] == "openai"
    assert "provider_upstream" not in usage_events[-1].payload
    assert result.node_report is not None
    assert result.node_report.usage is not None
    assert result.node_report.usage.input_tokens == 5
    assert result.node_report.usage.output_tokens == 6
    assert result.node_report.usage.total_tokens == 11
    assert result.node_report.usage.request_id == "req_gateway"
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
