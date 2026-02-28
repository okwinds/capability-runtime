"""
Agently → Skills Runtime SDK 的 LLM backend 适配器。

设计要点（非常重要）：
- SDK agent loop 需要完整的 OpenAI wire `messages[]`（含 tool_call_id/tool_calls 等字段）。
- 因此桥接层不能使用 Agently 的 PromptGenerator（Prompt.to_messages）做映射，否则会丢字段导致 tool 闭环失败。
- 本模块复用 Agently builtins 的 OpenAICompatible ModelRequester 作为“网络/SSE 传输层”，直接发送 wire payload。
- 解析阶段复用 SDK `ChatCompletionsSseParser`，确保 tool_calls delta 拼接口径不分叉。

对齐规格：
- `openspec/specs/upstream-bridge/spec.md`
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional, Protocol

from skills_runtime.core.agent import ChatBackend
from skills_runtime.llm.chat_sse import ChatCompletionsSseParser, ChatStreamEvent
from skills_runtime.llm.protocol import ChatRequest
from skills_runtime.tools.protocol import ToolSpec, tool_spec_to_openai_tool


class AgentlyRequester(Protocol):
    """
    requester 抽象（用于测试注入）。

    约束：
    - `generate_request_data()` 返回一个具备 `.data/.request_options/.request_url/...` 字段的对象
    - `request_model(request_data)` yield `(event, data)`，其中 data 为 SSE `data` 字符串或异常
    """

    def generate_request_data(self) -> Any:
        """生成请求载体对象（需包含 `.data` 与 `.request_options` 字段）。"""

        ...

    async def request_model(self, request_data: Any) -> AsyncIterator[tuple[str, Any]]:
        """发起流式请求并返回 `(event, data)` 迭代。"""

        ...


class AgentlyRequesterFactory(Protocol):
    """创建 requester 的工厂（用于测试注入与未来扩展）。"""

    def __call__(self) -> AgentlyRequester:
        """创建并返回一个 requester 实例。"""

        ...


@dataclass(frozen=True)
class AgentlyBackendConfig:
    """
    AgentlyChatBackend 的最小配置。

    参数：
    - `requester_factory`：默认使用 Agently OpenAICompatible；测试可注入 FakeRequester。
    """

    requester_factory: AgentlyRequesterFactory


class AgentlyChatBackend(ChatBackend):
    """
    SDK `ChatBackend` 的 Agently 适配实现。

    说明：
    - `stream_chat` 输入为 OpenAI wire `messages[]` 与 `tools[]`（ToolSpec）。
    - 输出为 SDK 的 `ChatStreamEvent`（text_delta/tool_calls/completed）。
    """

    def __init__(self, *, config: AgentlyBackendConfig) -> None:
        """创建 backend。"""

        self._config = config

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[ChatStreamEvent]:
        """
        发起一次 chat.completions streaming 并 yield `ChatStreamEvent`。

        参数：
        - `request`：上游 `ChatRequest` 参数包（包含 model/messages/tools 与可选推理参数）
        """

        requester = self._config.requester_factory()
        request_data = requester.generate_request_data()

        if not isinstance(request.messages, list):
            raise TypeError("messages must be a list[dict]")

        request_data.data["messages"] = request.messages
        request_data.request_options["model"] = request.model
        request_data.request_options["stream"] = True
        request_data.stream = True

        if request.temperature is not None:
            request_data.request_options["temperature"] = float(request.temperature)
        if request.max_tokens is not None:
            request_data.request_options["max_tokens"] = int(request.max_tokens)
        if request.top_p is not None:
            request_data.request_options["top_p"] = float(request.top_p)
        if request.response_format is not None:
            request_data.request_options["response_format"] = dict(request.response_format)

        # provider 特有扩展字段（best-effort 透传；冲突时以 request_options 显式字段为准）
        #
        # 重要：
        # - request.extra 可能包含“运行时回调/非 JSON 值”（例如 on_retry=function），它们不属于 wire payload；
        # - 这些值若被透传到 requester，可能导致 JSON 序列化失败并让 real 模式不可用。
        if isinstance(request.extra, dict) and request.extra:
            import json

            def _is_jsonable(value: Any) -> bool:
                """
                判断 value 是否可 JSON 序列化（最小、保守）。

                说明：
                - 我们不尝试做自定义 default 编码（避免改变 wire 契约语义）；
                - 不可序列化的字段将被跳过（fail-closed），避免 real 模式因 requester 序列化失败而崩溃。
                """

                try:
                    json.dumps(value)
                    return True
                except TypeError:
                    return False

            for k, v in request.extra.items():
                if k not in request_data.request_options:
                    # 过滤明显的非 wire 字段（以及所有不可 JSON 序列化值）
                    if k == "on_retry":
                        continue
                    if callable(v) or not _is_jsonable(v):
                        continue
                    request_data.request_options[k] = v

        tool_specs = request.tools or []
        tools_wire = [tool_spec_to_openai_tool(spec) for spec in tool_specs]
        if tools_wire:
            request_data.request_options["tools"] = tools_wire
            request_data.request_options.setdefault("tool_choice", "auto")
        else:
            # 某些 provider 对 tools=[] 敏感；无工具时直接移除该字段。
            request_data.request_options.pop("tools", None)

        parser = ChatCompletionsSseParser()
        saw_done = False

        async for event, data in requester.request_model(request_data):
            if event == "error":
                if isinstance(data, BaseException):
                    raise data
                raise RuntimeError(f"Agently requester error: {data!r}")

            # OpenAICompatible requester 通常 yield ("message", <sse.data>)
            if not isinstance(data, str):
                continue

            for ev in parser.feed_data(data):
                if ev.type == "completed":
                    saw_done = True
                yield ev

            if data.strip() in ("[DONE]", "DONE"):
                saw_done = True
                break

        if not saw_done:
            for ev in parser.finish():
                yield ev


def build_openai_compatible_requester_factory(*, agently_agent: Any) -> AgentlyRequesterFactory:
    """
    构造默认 requester_factory（复用 Agently OpenAICompatible builtins）。

    参数：
    - `agently_agent`：宿主提供的 Agently agent（需包含 `plugin_manager` 与 `settings`）。

    返回：
    - requester_factory：无参可调用对象，返回 OpenAICompatible requester 实例。
    """

    from agently.core import Prompt
    from agently.builtins.plugins.ModelRequester.OpenAICompatible import OpenAICompatible

    plugin_manager = getattr(agently_agent, "plugin_manager", None)
    settings = getattr(agently_agent, "settings", None)
    if plugin_manager is None or settings is None:
        raise TypeError("agently_agent must provide .plugin_manager and .settings")

    def _factory() -> AgentlyRequester:
        """按当前 agently settings 构建一次 requester。"""

        # Prompt 仅用于让 OpenAICompatible 读取 settings/plugin 配置并生成 request_data；
        # 真实 wire messages 将在 backend 层覆盖到 request_data.data["messages"]。
        prompt = Prompt(plugin_manager=plugin_manager, parent_settings=settings, name="capability-runtime-backend")
        prompt.set("input", "bridge")  # 避免 prompt 全空触发校验
        return OpenAICompatible(prompt, settings)

    return _factory
