from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pytest

from skills_runtime.llm.chat_sse import ChatStreamEvent
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall

from capability_runtime import (
    AgentIOSchema,
    AgentSpec,
    CapabilityKind,
    CapabilitySpec,
    CapabilityStatus,
    Runtime,
    RuntimeConfig,
    WorkflowSpec,
)


def _mk_agent(*, with_schema: bool = True) -> AgentSpec:
    return AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A", description="输出 JSON"),
        output_schema=(
            AgentIOSchema(
                fields={"title": "str", "summary": "str", "score": "int"},
                required=["title", "summary"],
            )
            if with_schema
            else None
        ),
    )


def _mk_runtime(
    tmp_path: Path,
    *,
    events: List[ChatStreamEvent],
    output_validation_mode: str = "warn",
) -> Runtime:
    backend = FakeChatBackend(calls=[FakeChatCall(events=events)])
    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=tmp_path,
            sdk_backend=backend,
            preflight_mode="off",
            output_validation_mode=output_validation_mode,  # type: ignore[arg-type]
        )
    )
    return rt


@pytest.mark.asyncio
async def test_run_records_structured_output_summary_when_output_schema_valid(tmp_path: Path) -> None:
    rt = _mk_runtime(
        tmp_path,
        events=[
            ChatStreamEvent(type="text_delta", text='{"title":"A","summary":"B","score":1}'),
            ChatStreamEvent(type="completed"),
        ],
    )
    rt.register(_mk_agent())

    out = await rt.run("A")

    assert out.status == CapabilityStatus.SUCCESS
    assert out.node_report is not None
    summary = out.node_report.meta.get("structured_output") or {}
    assert summary.get("ok") is True
    assert summary.get("schema_id") == "capability-runtime.agent_output_schema.v1:A"
    assert summary.get("required") == ["title", "summary"]
    assert summary.get("present_keys") == ["score", "summary", "title"]


@pytest.mark.asyncio
async def test_run_warn_mode_does_not_fail_on_invalid_json_but_records_structured_output_error(tmp_path: Path) -> None:
    rt = _mk_runtime(
        tmp_path,
        events=[ChatStreamEvent(type="text_delta", text="not-json"), ChatStreamEvent(type="completed")],
        output_validation_mode="warn",
    )
    rt.register(_mk_agent())

    out = await rt.run("A")

    assert out.status == CapabilityStatus.SUCCESS
    assert out.node_report is not None
    summary = out.node_report.meta.get("structured_output") or {}
    assert summary.get("ok") is False
    errors = summary.get("errors") or []
    assert errors and errors[0].get("kind") == "invalid_json"


@pytest.mark.asyncio
async def test_run_error_mode_fail_closed_when_required_field_missing(tmp_path: Path) -> None:
    rt = _mk_runtime(
        tmp_path,
        events=[
            ChatStreamEvent(type="text_delta", text='{"title":"A","score":1}'),
            ChatStreamEvent(type="completed"),
        ],
        output_validation_mode="error",
    )
    rt.register(_mk_agent())

    out = await rt.run("A")

    assert out.status == CapabilityStatus.FAILED
    assert out.node_report is not None
    assert out.node_report.reason == "structured_output_error"
    assert out.node_report.meta.get("structured_output_overrode_status") is True
    errors = (out.node_report.meta.get("structured_output") or {}).get("errors") or []
    assert any(err.get("kind") == "missing_required" for err in errors)


@pytest.mark.asyncio
async def test_run_structured_returns_normalized_dict_and_raw_output(tmp_path: Path) -> None:
    rt = _mk_runtime(
        tmp_path,
        events=[
            ChatStreamEvent(type="text_delta", text='{"title":"A","summary":"B","score":1}'),
            ChatStreamEvent(type="completed"),
        ],
    )
    rt.register(_mk_agent())

    out = await rt.run_structured("A")

    assert out.status == CapabilityStatus.SUCCESS
    assert out.output == {"title": "A", "summary": "B", "score": 1}
    assert out.metadata.get("raw_output") == '{"title":"A","summary":"B","score":1}'


@pytest.mark.asyncio
async def test_run_structured_returns_schema_missing_error_when_agent_has_no_output_schema(tmp_path: Path) -> None:
    rt = _mk_runtime(
        tmp_path,
        events=[ChatStreamEvent(type="text_delta", text='{"title":"A"}'), ChatStreamEvent(type="completed")],
    )
    rt.register(_mk_agent(with_schema=False))

    out = await rt.run_structured("A")

    assert out.status == CapabilityStatus.FAILED
    assert out.error_code == "STRUCTURED_OUTPUT_SCHEMA_MISSING"


@pytest.mark.asyncio
async def test_run_structured_returns_unsupported_kind_for_workflow(tmp_path: Path) -> None:
    rt = _mk_runtime(
        tmp_path,
        events=[ChatStreamEvent(type="text_delta", text='{"title":"A"}'), ChatStreamEvent(type="completed")],
    )
    rt.register(
        WorkflowSpec(base=CapabilitySpec(id="WF", kind=CapabilityKind.WORKFLOW, name="WF"), steps=[])
    )

    out = await rt.run_structured("WF")

    assert out.status == CapabilityStatus.FAILED
    assert out.error_code == "STRUCTURED_OUTPUT_UNSUPPORTED_KIND"


@pytest.mark.asyncio
async def test_run_structured_returns_invalid_error_when_final_output_breaks_contract(tmp_path: Path) -> None:
    rt = _mk_runtime(
        tmp_path,
        events=[ChatStreamEvent(type="text_delta", text='{"title":"A"}'), ChatStreamEvent(type="completed")],
        output_validation_mode="warn",
    )
    rt.register(_mk_agent())

    out = await rt.run_structured("A")

    assert out.status == CapabilityStatus.FAILED
    assert out.error_code == "STRUCTURED_OUTPUT_INVALID"
