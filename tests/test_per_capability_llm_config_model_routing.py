from __future__ import annotations

"""
离线回归：per-capability LLM model routing（AgentSpec.llm_config.model → SDK backend）。

目标：
- 当 AgentSpec.llm_config 包含 model 时：SDK backend 收到的 request.model 必须被覆写为该值。
- 当 llm_config 缺失/不含 model 时：不得做覆写（保持 runtime 默认行为）。
"""

import copy
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from skills_runtime.llm.chat_sse import ChatStreamEvent
from skills_runtime.llm.protocol import ChatRequest
from skills_runtime.tools.protocol import ToolSpec

from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec, CustomTool, Runtime, RuntimeConfig
from capability_runtime.sdk_lifecycle import (
    _ModelOverrideBackend,
    _PrecomposedMessagesBackend,
    _ResponseFormatOverrideBackend,
    _ToolChoiceOverrideBackend,
    _UsageTapBackend,
    _extract_tool_choice_override,
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
        self.messages: List[List[Dict[str, Any]]] = []
        self.tool_names: List[List[str]] = []

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[ChatStreamEvent]:
        self.models.append(getattr(request, "model", None))
        response_format = getattr(request, "response_format", None)
        self.response_formats.append(dict(response_format) if isinstance(response_format, dict) else None)
        extra = getattr(request, "extra", None)
        self.extras.append(extra if isinstance(extra, dict) else None)
        messages = getattr(request, "messages", None)
        self.messages.append([dict(item) for item in messages] if isinstance(messages, list) else [])
        tools = getattr(request, "tools", None)
        self.tool_names.append([tool.name for tool in tools] if isinstance(tools, list) else [])
        yield ChatStreamEvent(type="text_delta", text="ok")
        yield ChatStreamEvent(type="completed")


class _MutatingMessagesBackend:
    """
    测试用 ChatBackend：记录收到的 request.messages，然后故意篡改嵌套字段。

    该 backend 用于证明 `_PrecomposedMessagesBackend` 每次转发都生成独立嵌套副本，
    下游 backend 的原地修改不会污染 lifecycle 缓存或下一次 provider request。
    """

    def __init__(self) -> None:
        self.messages_before_mutation: List[List[Dict[str, Any]]] = []

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[ChatStreamEvent]:
        messages = getattr(request, "messages", None)
        if isinstance(messages, list):
            self.messages_before_mutation.append(copy.deepcopy(messages))
            messages[1]["content"][1]["image_url"]["url"] = "https://mutated.example/image.png"
            messages[2]["tool_calls"][0]["function"]["arguments"] = '{"mutated": true}'
            messages[3]["metadata"]["score"] = 0
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


def _agent_spec_with_prompt(
    *,
    agent_id: str,
    prompt_render_mode: str,
    prompt_profile: Optional[str] = None,
) -> AgentSpec:
    return AgentSpec(
        base=CapabilitySpec(
            id=agent_id,
            kind=CapabilityKind.AGENT,
            name=agent_id,
            description="This structured task text must not reach provider messages.",
        ),
        prompt_render_mode=prompt_render_mode,  # type: ignore[arg-type]
        prompt_profile=prompt_profile,
    )


def _multimodal_messages() -> List[Dict[str, Any]]:
    """
    构造覆盖多模态 content parts 与 assistant/tool extra fields 的 provider messages。

    返回：
    - 可直接作为 precomposed_messages 使用的 JSON-serializable message 列表。
    """

    return [
        {"role": "system", "content": "You inspect multimodal context."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Compare the images."},
                {"type": "image_url", "image_url": {"url": "https://example.test/a.png", "detail": "high"}},
                {"type": "image_url", "image_url": {"url": "https://example.test/b.png"}},
            ],
        },
        {
            "role": "assistant",
            "content": "I need the image metadata.",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "inspect_image", "arguments": '{"image": "a"}'},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "inspect_image",
            "content": '{"width": 1280}',
            "metadata": {"score": 1, "labels": ["diagram"]},
        },
    ]


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


def test_llm_config_tool_choice_invalid_type_fails_closed() -> None:
    with pytest.raises(ValueError, match="llm_config.tool_choice must be a string or dict"):
        _extract_tool_choice_override({"tool_choice": ["required"]})


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
async def test_tool_choice_required_is_preserved_after_tool_result_by_default() -> None:
    backend = _RecordingBackend()
    wrapped = _ToolChoiceOverrideBackend(backend=backend, tool_choice="required")

    async for _ in wrapped.stream_chat(
        ChatRequest(
            model="gpt-test",
            messages=[{"role": "user", "content": "call tool"}],
            tools=[],
        )
    ):
        pass
    async for _ in wrapped.stream_chat(
        ChatRequest(
            model="gpt-test",
            messages=[
                {"role": "user", "content": "call tool"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_emit_marker",
                            "type": "function",
                            "function": {"name": "emit_marker", "arguments": '{"marker":"ok"}'},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_emit_marker", "content": '{"ok":true}'},
            ],
            tools=[],
        )
    ):
        pass

    assert backend.extras[0]["tool_choice"] == "required"
    assert backend.extras[1]["tool_choice"] == "required"


@pytest.mark.asyncio
async def test_tool_choice_after_tool_result_compatibility_is_explicit_opt_in() -> None:
    backend = _RecordingBackend()
    wrapped = _ToolChoiceOverrideBackend(backend=backend, tool_choice="required", after_tool_result="none")

    async for _ in wrapped.stream_chat(
        ChatRequest(
            model="gpt-test",
            messages=[
                {"role": "user", "content": "call tool"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_emit_marker",
                            "type": "function",
                            "function": {"name": "emit_marker", "arguments": '{"marker":"ok"}'},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_emit_marker", "content": '{"ok":true}'},
            ],
            tools=[],
        )
    ):
        pass

    assert backend.extras[0]["tool_choice"] == "none"


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


@pytest.mark.asyncio
async def test_precomposed_messages_override_final_backend_request_messages(tmp_path: Path) -> None:
    """
    Prompt Rendering v1：precomposed_messages 必须让最终 backend 看到 host 提供的 messages。
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
    rt.register(
        _agent_spec_with_prompt(
            agent_id="agent.messages",
            prompt_render_mode="precomposed_messages",
            prompt_profile="generation_direct",
        )
    )
    messages = [
        {"role": "system", "content": "You are a generation engine."},
        {"role": "user", "content": "Write one clean sentence."},
    ]

    out = await rt.run(
        "agent.messages",
        input={
            "_runtime_prompt": {
                "messages": messages,
                "trace": {
                    "prompt_hash": "sha256:" + "c" * 64,
                    "composer_version": "composer@2",
                },
            }
        },
    )

    assert out.status.value == "success"
    assert backend.messages
    assert messages in backend.messages
    flattened = "\n".join(item.get("content", "") for request in backend.messages for item in request)
    assert "## 输入" not in flattened
    assert "## 系统指令" not in flattened
    assert "## 使用以下 Skills" not in flattened
    assert out.node_report is not None
    assert out.node_report.meta["prompt_render_mode"] == "precomposed_messages"
    assert out.node_report.meta["prompt_profile"] == "generation_direct"
    assert out.node_report.meta["prompt_hash"] == "sha256:" + "c" * 64
    assert out.node_report.meta["prompt_messages_count"] == 2
    assert out.node_report.meta["prompt_message_roles"] == ["system", "user"]
    assert out.node_report.meta["prompt_composer_version"] == "composer@2"
    assert "Write one clean sentence" not in out.node_report.model_dump_json()


@pytest.mark.asyncio
async def test_precomposed_multimodal_messages_override_final_backend_request_messages(tmp_path: Path) -> None:
    """
    Multimodal Boundary v1：多模态 messages 与 assistant/tool extra fields 必须等价到达 backend。
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
    rt.register(
        _agent_spec_with_prompt(
            agent_id="agent.multimodal.messages",
            prompt_render_mode="precomposed_messages",
            prompt_profile="generation_direct",
        )
    )
    messages = _multimodal_messages()

    out = await rt.run(
        "agent.multimodal.messages",
        input={"_runtime_prompt": {"messages": messages}},
    )

    assert out.status.value == "success"
    assert backend.messages
    assert messages in backend.messages
    observed = backend.messages[-1]
    assert observed[1]["content"] == messages[1]["content"]
    assert observed[2]["tool_calls"] == messages[2]["tool_calls"]
    assert observed[3]["tool_call_id"] == "call_1"
    assert observed[3]["name"] == "inspect_image"
    assert observed[3]["metadata"] == {"score": 1, "labels": ["diagram"]}


@pytest.mark.asyncio
async def test_precomposed_multimodal_messages_host_mutation_does_not_affect_request() -> None:
    """
    Multimodal Boundary v1：host 后续修改 nested content parts 不得污染 provider request。
    """

    backend = _RecordingBackend()
    messages = _multimodal_messages()
    expected = copy.deepcopy(messages)
    wrapped = _PrecomposedMessagesBackend(backend=backend, messages=messages)

    messages[1]["content"][1]["image_url"]["url"] = "https://host-mutated.example/a.png"
    messages[2]["tool_calls"][0]["function"]["arguments"] = '{"image": "mutated"}'
    messages[3]["metadata"]["labels"].append("host-mutated")

    async for _ in wrapped.stream_chat(ChatRequest(model="test-model", messages=[])):
        pass

    assert backend.messages == [expected]


@pytest.mark.asyncio
async def test_precomposed_multimodal_messages_backend_mutation_does_not_pollute_next_request() -> None:
    """
    Multimodal Boundary v1：backend 原地修改 request.messages 不得污染 lifecycle 缓存或下一次请求。
    """

    backend = _MutatingMessagesBackend()
    messages = _multimodal_messages()
    expected = copy.deepcopy(messages)
    wrapped = _PrecomposedMessagesBackend(backend=backend, messages=messages)

    async for _ in wrapped.stream_chat(ChatRequest(model="test-model", messages=[])):
        pass
    async for _ in wrapped.stream_chat(ChatRequest(model="test-model", messages=[])):
        pass

    assert backend.messages_before_mutation == [expected, expected]


@pytest.mark.asyncio
async def test_prompt_profile_generation_direct_reaches_sdk_prompt_config_and_hides_tools(
    tmp_path: Path,
) -> None:
    """
    Prompt Rendering v1：AgentSpec.prompt_profile 必须透传给 SDK，并让 generation_direct 默认隐藏 tools。
    """

    backend = _RecordingBackend()

    def _handler(**_: Any) -> Dict[str, Any]:
        return {"ok": True}

    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=tmp_path,
            preflight_mode="off",
            sdk_backend=backend,
            custom_tools=[
                CustomTool(
                    spec=ToolSpec(name="alpha_tool", description="alpha"),
                    handler=_handler,
                )
            ],
        )
    )
    rt.register(
        _agent_spec_with_prompt(
            agent_id="agent.profile",
            prompt_render_mode="direct_task_text",
            prompt_profile="generation_direct",
        )
    )

    out = await rt.run(
        "agent.profile",
        input={"_runtime_prompt": {"task_text": "Use no tools; answer directly."}},
    )

    assert out.status.value == "success"
    assert backend.tool_names
    assert [] in backend.tool_names
    overlay_dir = tmp_path / ".skills_runtime_sdk"
    residual_overlays = list(overlay_dir.glob("caprt_prompt_profile_*.yaml")) if overlay_dir.exists() else []
    assert residual_overlays == []
