from __future__ import annotations

"""
离线回归：per-capability LLM model routing（AgentSpec.llm_config.model → SDK backend）。

目标：
- 当 AgentSpec.llm_config 包含 model 时：SDK backend 收到的 request.model 必须被覆写为该值。
- 当 llm_config 缺失/不含 model 时：不得做覆写（保持 runtime 默认行为）。
"""

from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from skills_runtime.llm.chat_sse import ChatStreamEvent
from skills_runtime.llm.protocol import ChatRequest

from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec, Runtime, RuntimeConfig
from capability_runtime.sdk_lifecycle import (
    _ModelOverrideBackend,
    _ResponseFormatOverrideBackend,
    _ToolChoiceOverrideBackend,
    _UsageTapBackend,
)


class _RecordingBackend:
    """
    测试用 ChatBackend：记录每次调用的 request.model，并返回一个最小可完成的流。

    说明：
    - 不依赖外网；
    - 不引入 tool_calls，避免审批/工具链干扰本测试关注点。
    """

    def __init__(self) -> None:
        self.models: List[Optional[str]] = []
        self.response_formats: List[Optional[Dict[str, Any]]] = []
        self.extras: List[Optional[Dict[str, Any]]] = []

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[ChatStreamEvent]:
        self.models.append(getattr(request, "model", None))
        response_format = getattr(request, "response_format", None)
        self.response_formats.append(dict(response_format) if isinstance(response_format, dict) else None)
        extra = getattr(request, "extra", None)
        self.extras.append(extra if isinstance(extra, dict) else None)
        yield ChatStreamEvent(type="text_delta", text="ok")
        yield ChatStreamEvent(type="completed")


class _BrokenCloneRequest:
    """模拟 request 暴露 copy/model_copy，但内部复制总是失败。"""

    def __init__(self) -> None:
        self.model = "orig"
        self.extra = {"existing": True}
        self.response_format = {"type": "text"}

    def model_copy(self, *, update=None):  # type: ignore[no-untyped-def]
        _ = update
        raise RuntimeError("model_copy boom")

    def copy(self, *, update=None):  # type: ignore[no-untyped-def]
        _ = update
        raise RuntimeError("copy boom")


class _FallbackCloneRequest(_BrokenCloneRequest):
    """模拟 model_copy 失败、copy 成功的兼容对象。"""

    def copy(self, *, update=None):  # type: ignore[no-untyped-def]
        dup = _FallbackCloneRequest()
        if isinstance(update, dict):
            for key, value in update.items():
                setattr(dup, key, value)
        return dup


def _agent_spec(*, agent_id: str, llm_config: Optional[dict]) -> AgentSpec:
    return AgentSpec(
        base=CapabilitySpec(
            id=agent_id,
            kind=CapabilityKind.AGENT,
            name=agent_id,
            description="Just say ok.",
        ),
        llm_config=llm_config,
    )


@pytest.mark.asyncio
async def test_agent_spec_llm_config_model_overrides_backend_request_model(tmp_path: Path) -> None:
    backend = _RecordingBackend()
    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=tmp_path,
            preflight_mode="off",
            sdk_backend=backend,
        )
    )
    rt.register(_agent_spec(agent_id="agent.a", llm_config={"model": "model-a"}))
    rt.register(_agent_spec(agent_id="agent.b", llm_config={"model": "model-b"}))
    assert rt.validate() == []

    before = len(backend.models)
    out_a = await rt.run("agent.a", input={})
    assert out_a.node_report is not None
    after = len(backend.models)
    assert "model-a" in backend.models[before:after]

    before = len(backend.models)
    out_b = await rt.run("agent.b", input={})
    assert out_b.node_report is not None
    after = len(backend.models)
    assert "model-b" in backend.models[before:after]


@pytest.mark.asyncio
async def test_agent_spec_llm_config_absent_does_not_override_backend_request_model(tmp_path: Path) -> None:
    """
    回归：llm_config 缺失时不得强行覆写 model（应保持 runtime 默认行为）。
    """

    backend = _RecordingBackend()
    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=tmp_path,
            preflight_mode="off",
            sdk_backend=backend,
        )
    )
    rt.register(_agent_spec(agent_id="agent.none", llm_config=None))
    assert rt.validate() == []

    before = len(backend.models)
    out = await rt.run("agent.none", input={})
    assert out.node_report is not None
    after = len(backend.models)

    # 选择一个极不可能成为默认值的 sentinel，避免测试依赖上游默认 model 名称。
    sentinel = "caprt-test-model-override-sentinel"
    assert sentinel not in backend.models[before:after]


@pytest.mark.asyncio
async def test_agent_spec_llm_config_tool_choice_overrides_backend_request_extra(tmp_path: Path) -> None:
    backend = _RecordingBackend()
    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=tmp_path,
            preflight_mode="off",
            sdk_backend=backend,
        )
    )
    rt.register(_agent_spec(agent_id="agent.tc", llm_config={"tool_choice": "required"}))
    assert rt.validate() == []

    before = len(backend.extras)
    out = await rt.run("agent.tc", input={})
    assert out.node_report is not None
    after = len(backend.extras)

    observed = backend.extras[before:after]
    assert any((isinstance(ex, dict) and ex.get("tool_choice") == "required") for ex in observed)


@pytest.mark.asyncio
async def test_agent_spec_llm_config_response_format_overrides_backend_request_response_format(tmp_path: Path) -> None:
    backend = _RecordingBackend()
    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=tmp_path,
            preflight_mode="off",
            sdk_backend=backend,
        )
    )
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "agent_output",
            "schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
        },
    }
    rt.register(_agent_spec(agent_id="agent.rf", llm_config={"response_format": response_format}))
    assert rt.validate() == []

    before = len(backend.response_formats)
    out = await rt.run("agent.rf", input={})
    assert out.node_report is not None
    after = len(backend.response_formats)

    observed = backend.response_formats[before:after]
    assert response_format in observed


@pytest.mark.asyncio
async def test_agent_spec_llm_config_response_format_absent_does_not_override_backend_request_response_format(
    tmp_path: Path,
) -> None:
    backend = _RecordingBackend()
    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=tmp_path,
            preflight_mode="off",
            sdk_backend=backend,
        )
    )
    rt.register(_agent_spec(agent_id="agent.rf.none", llm_config=None))
    assert rt.validate() == []

    before = len(backend.response_formats)
    out = await rt.run("agent.rf.none", input={})
    assert out.node_report is not None
    after = len(backend.response_formats)

    sentinel = {
        "type": "json_schema",
        "json_schema": {"name": "caprt-test-response-format-override-sentinel"},
    }
    assert sentinel not in backend.response_formats[before:after]


@pytest.mark.asyncio
async def test_model_override_request_clone_failure_fails_closed_and_does_not_forward() -> None:
    backend = _RecordingBackend()
    wrapped = _ModelOverrideBackend(backend=backend, model="model-fail")

    with pytest.raises(Exception):
        async for _ in wrapped.stream_chat(_BrokenCloneRequest()):  # type: ignore[arg-type]
            pass

    assert backend.models == []


@pytest.mark.asyncio
async def test_tool_choice_override_request_clone_failure_fails_closed_and_does_not_forward() -> None:
    backend = _RecordingBackend()
    wrapped = _ToolChoiceOverrideBackend(backend=backend, tool_choice="required")

    with pytest.raises(Exception):
        async for _ in wrapped.stream_chat(_BrokenCloneRequest()):  # type: ignore[arg-type]
            pass

    assert backend.extras == []


@pytest.mark.asyncio
async def test_response_format_override_request_clone_failure_fails_closed_and_does_not_forward() -> None:
    backend = _RecordingBackend()
    wrapped = _ResponseFormatOverrideBackend(
        backend=backend,
        response_format={"type": "json_schema", "json_schema": {"name": "demo"}},
    )

    with pytest.raises(Exception):
        async for _ in wrapped.stream_chat(_BrokenCloneRequest()):  # type: ignore[arg-type]
            pass

    assert backend.response_formats == []


@pytest.mark.asyncio
async def test_usage_tap_backend_falls_back_to_copy_when_model_copy_fails() -> None:
    backend = _RecordingBackend()
    wrapped = _UsageTapBackend(backend=backend)

    async for _ in wrapped.stream_chat(_FallbackCloneRequest()):  # type: ignore[arg-type]
        pass

    assert backend.extras
    assert any(isinstance(extra, dict) and "_caprt_usage_sink" in extra for extra in backend.extras)
