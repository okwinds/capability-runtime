"""
Agently → Skills Runtime SDK 的 LLM backend 适配器。

设计要点（非常重要）：
- SDK agent loop 需要完整的 OpenAI wire `messages[]`（含 tool_call_id/tool_calls 等字段）。
- 因此桥接层不能使用 Agently 的 PromptGenerator（Prompt.to_messages）做映射，否则会丢字段导致 tool 闭环失败。
- 本模块复用 Agently builtins 的 OpenAICompatible ModelRequester 作为“网络/SSE 传输层”，直接发送 wire payload。
- 解析阶段复用 SDK `ChatCompletionsSseParser`，确保 tool_calls delta 拼接口径不分叉。

对齐规格：
- `docs/specs/agently-backend-stream-event-ordering-v1.md`
- `docs/specs/per-capability-llm-config-v1.md`
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional, Protocol, cast

from skills_runtime.llm.chat_sse import ChatCompletionsSseParser, ChatStreamEvent
from skills_runtime.llm.protocol import ChatBackend, ChatRequest
from skills_runtime.tools.protocol import ToolSpec, tool_spec_to_openai_tool

from ..logging_utils import log_suppressed_exception


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


def _usage_int(value: Any) -> Optional[int]:
    """把 usage 数值归一为非负 int；无法识别时返回 None。"""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _normalize_usage_payload(*, usage: Any, model: Any = None) -> Optional[Dict[str, Any]]:
    """
    把 provider usage 归一为 capability-runtime 的 `llm_usage` payload 形状。

    返回：
    - `None`：无法提取任何有效 usage 字段
    - `dict`：`model/input_tokens/output_tokens/total_tokens`
    """

    if not isinstance(usage, dict):
        return None

    model_text = model.strip() if isinstance(model, str) and model.strip() else None
    input_tokens = _usage_int(usage.get("input_tokens"))
    if input_tokens is None:
        input_tokens = _usage_int(usage.get("prompt_tokens"))

    output_tokens = _usage_int(usage.get("output_tokens"))
    if output_tokens is None:
        output_tokens = _usage_int(usage.get("completion_tokens"))

    total_tokens = _usage_int(usage.get("total_tokens"))
    payload = {
        "model": model_text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }
    return payload if any(value is not None for value in payload.values()) else None


def _extract_usage_payload_from_sse_data(data: str) -> Optional[Dict[str, Any]]:
    """
    从原始 SSE `data` 字符串中提取 usage 摘要。

    说明：
    - bridge 模式仅做 best-effort；
    - 解析失败/无 usage 时返回 None，不影响主链。
    """

    raw = str(data or "").strip()
    if not raw or raw in ("[DONE]", "DONE"):
        return None
    try:
        obj = json.loads(raw)
    except Exception as exc:
        log_suppressed_exception(
            context="parse_usage_payload_json",
            exc=exc,
            extra={"raw_len": len(raw)},
        )
        return None
    if not isinstance(obj, dict):
        return None
    return _normalize_usage_payload(usage=obj.get("usage"), model=obj.get("model"))


def _merge_stream_options_for_usage(value: Any) -> Dict[str, Any]:
    """
    为 streaming 请求补齐 `include_usage=true`，同时保留已有 stream_options。

    说明：
    - OpenAICompatible provider 若不支持该字段，应在 provider/requester 侧 fail-open；
    - 本函数只负责把请求事实补齐，不在此处做兼容分支判断。
    """

    merged = dict(value) if isinstance(value, dict) else {}
    merged.setdefault("include_usage", True)
    return merged


def _should_retry_without_stream_options(error: Any) -> bool:
    """判断 provider 拒绝 `stream_options/include_usage` 时是否应 fail-open 重试。"""

    message = str(error or "").lower()
    if not message:
        return False
    mentions_stream_options = "stream_options" in message or "include_usage" in message
    mentions_unsupported = any(
        token in message
        for token in (
            "unknown parameter",
            "unsupported",
            "not support",
            "not supported",
            "invalid parameter",
            "extra inputs are not permitted",
            "400",
            "422",
        )
    )
    return mentions_stream_options and mentions_unsupported


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

        usage_sink = None
        if isinstance(getattr(request, "extra", None), dict):
            candidate_sink = request.extra.get("_caprt_usage_sink")
            if callable(candidate_sink):
                usage_sink = candidate_sink

        if not isinstance(request.messages, list):
            raise TypeError("messages must be a list[dict]")
        include_usage_enabled = True
        for attempt in range(2):
            requester = self._config.requester_factory()
            request_data = requester.generate_request_data()
            request_data.data["messages"] = request.messages
            request_data.request_options["model"] = request.model
            request_data.request_options["stream"] = True
            request_data.stream = True

            tool_specs: List[ToolSpec] = list(request.tools or [])
            tool_choice_target_tool_name: Optional[str] = None

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
                    # 过滤明显的非 wire 字段（以及所有不可 JSON 序列化值）
                    if k == "on_retry":
                        continue
                    if callable(v) or not _is_jsonable(v):
                        continue

                    # 覆写优先级（spec 要求）：
                    # - per-run llm_config 会写入 request.extra["tool_choice"]
                    # - 即使底层 requester/backend 已预置 tool_choice（例如默认 "auto"），也必须被本覆写覆盖
                    if k == "tool_choice":
                        if isinstance(v, dict):
                            # OpenAI 新格式：{"type":"function","function":{"name":"..."}}
                            # 某些 OpenAICompatible server 不支持 tool_choice.function，会直接 400；
                            # 兼容策略：归一化为 tool_choice="required"，并（若可定位）过滤 tools 以避免选错工具。
                            function = v.get("function") if isinstance(v.get("function"), dict) else None
                            if function is not None:
                                name = function.get("name")
                                if isinstance(name, str) and name:
                                    tool_choice_target_tool_name = name
                            request_data.request_options[k] = "required"
                        else:
                            request_data.request_options[k] = v
                        continue

                    if k not in request_data.request_options:
                        request_data.request_options[k] = v

            if include_usage_enabled:
                request_data.request_options["stream_options"] = _merge_stream_options_for_usage(
                    request_data.request_options.get("stream_options")
                )
            else:
                request_data.request_options.pop("stream_options", None)

            if tool_choice_target_tool_name:
                matched = [spec for spec in tool_specs if spec.name == tool_choice_target_tool_name]
                if matched:
                    tool_specs = matched

            tools_wire = [tool_spec_to_openai_tool(spec) for spec in tool_specs]
            if tools_wire:
                request_data.request_options["tools"] = tools_wire
                request_data.request_options.setdefault("tool_choice", "auto")
            else:
                # 某些 provider 对 tools=[] 敏感；无工具时直接移除该字段。
                request_data.request_options.pop("tools", None)

            parser = ChatCompletionsSseParser()
            deferred_completed: Optional[ChatStreamEvent] = None

            # 兼容：不同版本/实现的 requester 可能返回：
            # - async iterator（可直接 async for）
            # - coroutine -> async iterator（需要 await 一次再 async for）
            stream_or_coro = requester.request_model(request_data)
            stream: AsyncIterator[tuple[str, Any]]
            retry_without_stream_options = False
            try:
                if hasattr(stream_or_coro, "__aiter__"):
                    stream = cast(AsyncIterator[tuple[str, Any]], stream_or_coro)
                else:
                    stream = await stream_or_coro

                async for event, data in stream:
                    if event == "error":
                        error = data if isinstance(data, BaseException) else RuntimeError(f"Agently requester error: {data!r}")
                        if include_usage_enabled and attempt == 0 and _should_retry_without_stream_options(error):
                            retry_without_stream_options = True
                            log_suppressed_exception(
                                context="agently_backend_include_usage_retry",
                                exc=error,
                                extra={"retry_without_stream_options": True},
                            )
                            break
                        raise error

                    # OpenAICompatible requester 通常 yield ("message", <sse.data>)
                    if not isinstance(data, str):
                        continue

                    usage_payload = _extract_usage_payload_from_sse_data(data)
                    if usage_payload is not None and usage_sink is not None:
                        try:
                            usage_sink(dict(usage_payload))
                        except Exception as sink_exc:
                            log_suppressed_exception(
                                context="usage_sink_callback",
                                exc=sink_exc,
                                extra={"source": "agently_backend"},
                            )

                    for ev in parser.feed_data(data):
                        # 关键不变量：
                        # 某些 OpenAICompatible server 的 SSE 序列可能是：
                        # - delta.tool_calls ...（累计中）
                        # - finish_reason="stop" → parser 先 emit completed
                        # - [DONE] → parser 才 flush tool_calls
                        #
                        # 若我们把 completed 立即 yield，上游消费端可能在 completed 后停止消费，
                        # 从而错过后续 tool_calls，最终表现为 NodeReport.tool_calls 为空。
                        #
                        # 因此：completed 事件必须延迟到“确认不会再有 tool_calls”后再产出。
                        if ev.type == "completed":
                            deferred_completed = ev
                            continue
                        yield ev

                    if data.strip() in ("[DONE]", "DONE"):
                        break
            except Exception as error:
                if include_usage_enabled and attempt == 0 and _should_retry_without_stream_options(error):
                    retry_without_stream_options = True
                    log_suppressed_exception(
                        context="agently_backend_include_usage_retry",
                        exc=error,
                        extra={"retry_without_stream_options": True, "raised_directly": True},
                    )
                else:
                    raise

            if retry_without_stream_options:
                include_usage_enabled = False
                continue

            # 注意：即使已看到 [DONE]，也必须调用 parser.finish()：
            # - 某些实现可能不会在 feed_data("[DONE]") 时 flush tool_calls；
            # - 若跳过 finish()，会出现“tool_calls 丢失/NodeReport.tool_calls 为空”的假阴性。
            for ev in parser.finish():
                if ev.type == "completed":
                    # 不用 finish() 的 eof 覆盖真实 stop（若已看到 stop completed）
                    if deferred_completed is None:
                        deferred_completed = ev
                    continue
                yield ev

            if deferred_completed is not None:
                yield deferred_completed
            return


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
