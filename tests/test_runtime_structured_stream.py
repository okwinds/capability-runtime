from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from skills_runtime.llm.chat_sse import ChatStreamEvent
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall

from capability_runtime import AgentIOSchema, AgentSpec, CapabilityKind, CapabilitySpec, Runtime, RuntimeConfig


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
