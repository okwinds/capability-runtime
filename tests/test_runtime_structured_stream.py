from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

import pytest

from skills_runtime.llm.chat_sse import ChatStreamEvent
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall

from capability_runtime import AgentIOSchema, AgentSpec, CapabilityKind, CapabilitySpec, Runtime, RuntimeConfig


class _FakeResponsesRequestData:
    def __init__(self) -> None:
        self.data = {"input": []}
        self.request_options: dict[str, Any] = {}
        self.request_url = "http://example.invalid/responses"
        self.headers: dict[str, str] = {}
        self.client_options: dict[str, Any] = {}
        self.stream = True


class _FakeResponsesRequester:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    def generate_request_data(self) -> _FakeResponsesRequestData:
        return _FakeResponsesRequestData()

    async def request_model(self, request_data: _FakeResponsesRequestData):
        _ = request_data
        yield ("response.completed", self.payload)


class _FakeResponsesRequesterFactory:
    requester_strategy = "responses"

    def __init__(self, payload: str) -> None:
        self.payload = payload

    def __call__(self) -> _FakeResponsesRequester:
        return _FakeResponsesRequester(self.payload)


def _mk_runtime(tmp_path: Path, *, events: List[ChatStreamEvent]) -> Runtime:
    backend = FakeChatBackend(calls=[FakeChatCall(events=events)])
    return Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=tmp_path,
            sdk_backend=backend,
            preflight_mode="off",
        )
    )


def _register_structured_agent(rt: Runtime) -> None:
    rt.register(
        AgentSpec(
            base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A", description="输出结构化 JSON"),
            output_schema=AgentIOSchema(
                fields={"title": "str", "summary": "str"},
                required=["title", "summary"],
            ),
        )
    )


def _mk_responses_bridge_runtime(tmp_path: Path, *, output_text: str) -> Runtime:
    payload = json.dumps(
        {
            "type": "response.completed",
            "response": {
                "id": "resp_structured",
                "model": "gpt-responses",
                "status": "completed",
                "output_text": output_text,
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            },
        }
    )
    return Runtime(
        RuntimeConfig(
            mode="bridge",
            workspace_root=tmp_path,
            preflight_mode="off",
            provider_requester_factory=_FakeResponsesRequesterFactory(payload),
            requester_strategy="responses",
        )
    )


def test_responses_bridge_does_not_add_second_structured_output_public_api() -> None:
    """
    Responses mode 只能增强既有 structured stream surface，不允许新增第二套结构化输出 API。
    """

    import capability_runtime as caprt

    forbidden = [
        "ResponseParser",
        "ResponsesStructuredParser",
        "run_responses_structured",
        "run_responses_structured_stream",
    ]
    for name in forbidden:
        assert not hasattr(caprt, name), name


@pytest.mark.asyncio
async def test_run_structured_stream_emits_started_text_snapshot_field_updates_and_terminal(tmp_path: Path) -> None:
    rt = _mk_runtime(
        tmp_path,
        events=[
            ChatStreamEvent(type="text_delta", text='{"title":"A","summary":"B"}'),
            ChatStreamEvent(type="text_delta", text=" "),
            ChatStreamEvent(type="completed"),
        ],
    )
    _register_structured_agent(rt)

    items = [item async for item in rt.run_structured_stream("A")]

    assert items[0].type == "started"
    assert items[-1].type == "terminal"
    assert items[-1].status == "success"
    assert items[-1].output == {"title": "A", "summary": "B"}
    assert [item.type for item in items].count("text_delta") == 2
    assert [item.type for item in items].count("object_snapshot") >= 1
    field_updates = [item for item in items if item.type == "field_updated"]
    assert [(item.field, item.value) for item in field_updates] == [("title", "A"), ("summary", "B")]


@pytest.mark.asyncio
async def test_run_structured_stream_schema_missing_fails_after_started(tmp_path: Path) -> None:
    rt = _mk_runtime(
        tmp_path,
        events=[ChatStreamEvent(type="text_delta", text='{"title":"A"}'), ChatStreamEvent(type="completed")],
    )
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))

    items = [item async for item in rt.run_structured_stream("A")]

    assert [item.type for item in items] == ["started", "terminal"]
    assert items[-1].status == "failed"
    assert items[-1].error_code == "STRUCTURED_OUTPUT_SCHEMA_MISSING"


@pytest.mark.asyncio
async def test_run_structured_stream_invalid_json_returns_failed_terminal(tmp_path: Path) -> None:
    rt = _mk_runtime(
        tmp_path,
        events=[ChatStreamEvent(type="text_delta", text="oops"), ChatStreamEvent(type="completed")],
    )
    _register_structured_agent(rt)

    items = [item async for item in rt.run_structured_stream("A")]

    assert items[0].type == "started"
    assert items[-1].type == "terminal"
    assert items[-1].status == "failed"
    assert items[-1].error_code == "STRUCTURED_OUTPUT_INVALID"


@pytest.mark.asyncio
async def test_run_structured_stream_without_text_deltas_still_returns_started_and_terminal(tmp_path: Path) -> None:
    def handler(_spec, _input):
        return '{"title":"A","summary":"B"}'

    rt = Runtime(RuntimeConfig(mode="mock", workspace_root=tmp_path, mock_handler=handler))
    _register_structured_agent(rt)

    items = [item async for item in rt.run_structured_stream("A")]

    assert [item.type for item in items] == ["started", "terminal"]
    assert items[-1].status == "success"
    assert items[-1].output == {"title": "A", "summary": "B"}


@pytest.mark.asyncio
async def test_run_structured_stream_responses_bridge_uses_existing_surface(tmp_path: Path) -> None:
    """Responses bridge 必须增强既有 run_structured_stream surface，而不是新增第二套 API。"""

    rt = _mk_responses_bridge_runtime(tmp_path, output_text='{"title":"A","summary":"B"}')
    _register_structured_agent(rt)

    items = [item async for item in rt.run_structured_stream("A")]

    assert items[0].type == "started"
    assert items[-1].type == "terminal"
    assert items[-1].status == "success"
    assert items[-1].output == {"title": "A", "summary": "B"}
    assert [item.type for item in items].count("text_delta") == 1
    assert [item.type for item in items].count("object_snapshot") >= 1


@pytest.mark.asyncio
async def test_run_structured_stream_responses_bridge_parser_failure_uses_existing_terminal(tmp_path: Path) -> None:
    """Responses bridge 解析失败也应走既有 structured terminal fail-closed 语义。"""

    rt = _mk_responses_bridge_runtime(tmp_path, output_text="not-json")
    _register_structured_agent(rt)

    items = [item async for item in rt.run_structured_stream("A")]

    assert items[0].type == "started"
    assert items[-1].type == "terminal"
    assert items[-1].status == "failed"
    assert items[-1].error_code == "STRUCTURED_OUTPUT_INVALID"
