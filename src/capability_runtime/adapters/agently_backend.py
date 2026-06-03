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
from typing import Any, AsyncIterator, Collection, Dict, List, Optional, Protocol, cast
from urllib.parse import urlparse

from skills_runtime.llm.chat_sse import ChatCompletionsSseParser, ChatStreamEvent
from skills_runtime.llm.protocol import ChatBackend, ChatRequest
from skills_runtime.tools.protocol import ToolCall, ToolSpec, tool_spec_to_openai_tool

from ..config import ProviderRequesterFactory, ProviderRequesterStrategy
from ..errors import ProviderStreamTerminalError
from ..logging_utils import log_suppressed_exception
from ..utils.usage import _usage_int


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
    - `requester_strategy`：Agently requester 策略；默认保留 chat.completions legacy 路径。
    """

    requester_factory: AgentlyRequesterFactory
    requester_strategy: ProviderRequesterStrategy = "chat_completions"


def _parse_tool_call_arguments(raw_arguments: str) -> Dict[str, Any]:
    """解析 tool call arguments；非法 JSON 或非 object 必须 fail-closed。"""

    if not raw_arguments.strip():
        return {}
    try:
        parsed = json.loads(raw_arguments)
    except Exception as exc:
        log_suppressed_exception(
            context="parse_responses_tool_call_arguments",
            exc=exc,
            extra={"raw_len": len(raw_arguments)},
        )
        raise ValueError("Responses function_call arguments must be a JSON object") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Responses function_call arguments must be a JSON object")
    return parsed


def _responses_content_parts(content: Any) -> List[Dict[str, Any]]:
    """把 OpenAI chat message content 归一为 Responses input content parts。"""

    if isinstance(content, list):
        parts: List[Dict[str, Any]] = []
        for part in content:
            if isinstance(part, str):
                parts.append({"type": "input_text", "text": part})
                continue
            if not isinstance(part, dict):
                parts.append({"type": "input_text", "text": str(part)})
                continue
            part_type = part.get("type")
            if part_type == "text":
                parts.append({"type": "input_text", "text": str(part.get("text", ""))})
            elif part_type == "image_url":
                image_url = part.get("image_url")
                detail = None
                if isinstance(image_url, dict):
                    detail = image_url.get("detail")
                    image_url = image_url.get("url")
                if isinstance(image_url, str) and image_url.strip():
                    image_part: Dict[str, Any] = {"type": "input_image", "image_url": image_url.strip()}
                    if isinstance(detail, str) and detail.strip():
                        image_part["detail"] = detail.strip()
                    parts.append(image_part)
                else:
                    parts.append({"type": "input_text", "text": str(part.get("text", ""))})
            elif part_type in ("input_text", "input_image", "input_file"):
                parts.append(dict(part))
            else:
                parts.append({"type": "input_text", "text": str(part.get("text", ""))})
        return parts
    return [{"type": "input_text", "text": str(content or "")}]


def _responses_input_from_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把 chat.completions messages 显式编译为 Responses `input`。"""

    items: List[Dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "user"))
        assistant_tool_calls = role == "assistant" and isinstance(message.get("tool_calls"), list)
        if assistant_tool_calls:
            content = message.get("content")
            if content not in (None, ""):
                items.append(
                    {
                        "type": "message",
                        "role": role,
                        "content": _responses_content_parts(content),
                    }
                )
        if assistant_tool_calls:
            for tool_call in message.get("tool_calls") or []:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
                call_id = str(tool_call.get("id") or tool_call.get("call_id") or "").strip()
                name = str(function.get("name") or tool_call.get("name") or "").strip()
                arguments = function.get("arguments", tool_call.get("arguments", ""))
                if not call_id or not name:
                    continue
                items.append(
                    {
                        "type": "function_call",
                        "call_id": call_id,
                        "name": name,
                        "arguments": str(arguments or ""),
                    }
                )
            continue
        if role == "tool":
            call_id = str(message.get("tool_call_id") or message.get("call_id") or "").strip()
            if call_id:
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": str(message.get("content") or ""),
                    }
                )
            continue
        items.append(
            {
                "type": "message",
                "role": role,
                "content": _responses_content_parts(message.get("content", "")),
            }
        )
    return items


def _responses_tool_from_spec(spec: ToolSpec) -> Dict[str, Any]:
    """把 SDK ToolSpec 编译为 Responses function tool wire 形状。"""

    openai_tool = tool_spec_to_openai_tool(spec)
    function = openai_tool.get("function") if isinstance(openai_tool, dict) else None
    if not isinstance(function, dict):
        return dict(openai_tool)
    return {
        "type": "function",
        "name": str(function.get("name", "")),
        "description": str(function.get("description", "")),
        "parameters": dict(function.get("parameters") or {}),
        "strict": bool(function.get("strict", False)),
    }


def _responses_tool_choice(value: Any) -> Any:
    """把 chat-style named tool_choice 归一为 Responses function tool_choice。"""

    if not isinstance(value, dict):
        return value
    function = value.get("function")
    if isinstance(function, dict):
        name = str(function.get("name") or "").strip()
        if name:
            return {"type": "function", "name": name}
    return value


def _is_jsonable_extra_value(value: Any, *, _seen: set[int] | None = None) -> bool:
    """判断 request.extra 值是否适合作为 provider wire option 透传。"""

    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, dict):
        seen = _seen if _seen is not None else set()
        oid = id(value)
        if oid in seen:
            return False
        seen.add(oid)
        try:
            return all(isinstance(k, str) and _is_jsonable_extra_value(v, _seen=seen) for k, v in value.items())
        finally:
            seen.remove(oid)
    if isinstance(value, (list, tuple)):
        seen = _seen if _seen is not None else set()
        oid = id(value)
        if oid in seen:
            return False
        seen.add(oid)
        try:
            return all(_is_jsonable_extra_value(v, _seen=seen) for v in value)
        finally:
            seen.remove(oid)
    return False


def _is_responses_empty_stream_error(error: BaseException) -> bool:
    """识别 Responses provider streaming 空流终止错误，仅用于一次 non-stream fallback。"""

    message = str(error).strip()
    if message == "async generator raised StopAsyncIteration":
        return True
    return "Detail: async generator raised StopAsyncIteration" in message


def _normalize_usage_payload(
    *,
    usage: Any,
    model: Any = None,
    request_id: Any = None,
    provider: Any = None,
    provider_transport: Any = None,
    allow_metadata_only: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    把 provider usage 归一为 capability-runtime 的 `llm_usage` payload 形状。

    返回：
    - `None`：无法提取任何有效 usage 字段
    - `dict`：`model/input_tokens/output_tokens/total_tokens/request_id/provider`
    """

    model_text = model.strip() if isinstance(model, str) and model.strip() else None
    if not isinstance(usage, dict) and not allow_metadata_only:
        return None

    usage_dict = usage if isinstance(usage, dict) else {}
    input_tokens = _usage_int(usage_dict.get("input_tokens"))
    if input_tokens is None:
        input_tokens = _usage_int(usage_dict.get("prompt_tokens"))

    output_tokens = _usage_int(usage_dict.get("output_tokens"))
    if output_tokens is None:
        output_tokens = _usage_int(usage_dict.get("completion_tokens"))

    total_tokens = _usage_int(usage_dict.get("total_tokens"))
    payload = {
        "model": model_text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "request_id": request_id.strip() if isinstance(request_id, str) and request_id.strip() else None,
        "provider": provider.strip() if isinstance(provider, str) and provider.strip() else None,
        "provider_transport": (
            provider_transport.strip()
            if isinstance(provider_transport, str) and provider_transport.strip()
            else None
        ),
    }
    return payload if any(value is not None for value in payload.values()) else None


def _provider_terminal_error_from_response(
    *,
    payload_type: str,
    response: Dict[str, Any],
    request_model: Any,
) -> ProviderStreamTerminalError:
    """把 Responses terminal failure/incomplete payload 归一为 fail-closed error。"""

    error_obj = response.get("error")
    error = error_obj if isinstance(error_obj, dict) else {}
    code = str(error.get("code") or response.get("status") or payload_type)
    message = str(error.get("message") or f"Responses stream ended with {payload_type}")
    request_id = str(response.get("id")) if response.get("id") is not None else None
    provider = str(response.get("provider")) if response.get("provider") is not None else None
    model = str(response.get("model") or request_model) if response.get("model") is not None or request_model is not None else None
    status = "incomplete" if payload_type in {"response.incomplete", "response.cancelled"} else "failed"
    reason = "cancelled" if payload_type == "response.cancelled" else code
    completion_reason = payload_type.replace("response.", "response_")
    if request_id is not None:
        message = f"{message} (request_id={request_id})"
    return ProviderStreamTerminalError(
        message=f"{code}: {message}",
        status=status,
        reason=reason,
        completion_reason=completion_reason,
        error_code="PROVIDER_STREAM_CANCELLED" if payload_type == "response.cancelled" else "PROVIDER_STREAM_TERMINAL",
        request_id=request_id,
        provider=provider,
        provider_transport="responses",
        model=model,
    )


def _extract_usage_payload_from_sse_data(data: str, *, request_model: Any = None) -> Optional[Dict[str, Any]]:
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
    request_id = obj.get("request_id")
    if not (isinstance(request_id, str) and request_id.strip()):
        request_id = obj.get("id")
    return _normalize_usage_payload(
        usage=obj.get("usage"),
        model=obj.get("model") or request_model,
        request_id=request_id,
        provider=obj.get("provider"),
        provider_transport="chat_completions",
    )


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

        if self._config.requester_strategy == "responses":
            async for event in self._stream_responses_chat(request):
                yield event
            return

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
                for k, v in request.extra.items():
                    # 过滤明显的非 wire 字段（以及所有不可 JSON 序列化值）
                    if k == "on_retry":
                        continue
                    if callable(v) or not _is_jsonable_extra_value(v):
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
                if not matched:
                    raise ValueError(f"tool_choice target tool not found: {tool_choice_target_tool_name}")
                tool_specs = matched

            tools_wire = [tool_spec_to_openai_tool(spec) for spec in tool_specs]
            if tools_wire:
                request_data.request_options["tools"] = tools_wire
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

                    usage_payload = _extract_usage_payload_from_sse_data(data, request_model=request.model)
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

    async def _stream_responses_chat(self, request: ChatRequest) -> AsyncIterator[ChatStreamEvent]:
        """
        发起一次 Responses streaming 请求并归一化为 SDK `ChatStreamEvent`。

        Agently `OpenAIResponsesCompatible` 的 stream event 与 chat.completions SSE 不同；
        本方法只在 adapter 内部做语义归一，不新增第二套下游 API。
        """

        if not isinstance(request.messages, list):
            raise TypeError("messages must be a list[dict]")

        usage_sink = None
        if isinstance(getattr(request, "extra", None), dict):
            candidate_sink = request.extra.get("_caprt_usage_sink")
            if callable(candidate_sink):
                usage_sink = candidate_sink

        def _new_requester_and_data(*, stream: bool) -> tuple[AgentlyRequester, Any]:
            requester = self._config.requester_factory()
            request_data = requester.generate_request_data()
            request_data.data["input"] = _responses_input_from_messages(request.messages)
            request_data.request_options["model"] = request.model
            request_data.request_options["stream"] = bool(stream)
            request_data.stream = bool(stream)

            if request.temperature is not None:
                request_data.request_options["temperature"] = float(request.temperature)
            if request.max_tokens is not None:
                request_data.request_options["max_output_tokens"] = int(request.max_tokens)
            if request.top_p is not None:
                request_data.request_options["top_p"] = float(request.top_p)
            if request.response_format is not None:
                request_data.request_options["text"] = {"format": dict(request.response_format)}

            if isinstance(request.extra, dict):
                for key, value in request.extra.items():
                    if key.startswith("_caprt_") or key == "on_retry":
                        continue
                    if callable(value) or not _is_jsonable_extra_value(value):
                        continue
                    if key == "tool_choice":
                        request_data.request_options["tool_choice"] = _responses_tool_choice(value)
                        continue
                    if key not in request_data.request_options:
                        request_data.request_options[key] = value

            tools_wire = [_responses_tool_from_spec(spec) for spec in list(request.tools or [])]
            if tools_wire:
                request_data.request_options["tools"] = tools_wire
            else:
                request_data.request_options.pop("tools", None)
            return requester, request_data

        requester, request_data = _new_requester_and_data(stream=True)

        tool_states: Dict[str, Dict[str, Any]] = {}
        emitted_tool_calls: set[str] = set()
        emitted_text = ""

        async def _request_stream() -> AsyncIterator[tuple[str, Any]]:
            stream_or_coro = requester.request_model(request_data)
            if hasattr(stream_or_coro, "__aiter__"):
                return cast(AsyncIterator[tuple[str, Any]], stream_or_coro)
            return await stream_or_coro

        def _state_for(call_id: str, *, output_index: Any = None) -> Dict[str, Any]:
            index = output_index if isinstance(output_index, int) else len(tool_states)
            return tool_states.setdefault(
                call_id,
                {
                    "call_id": call_id,
                    "index": index,
                    "name": "",
                    "arguments": "",
                },
            )

        def _tool_event_from_state(state: Dict[str, Any]) -> ChatStreamEvent | None:
            call_id = str(state.get("call_id", "")).strip()
            if not call_id:
                raise _malformed_tool_call_error("Responses function_call call_id is missing")
            if call_id in emitted_tool_calls:
                return None
            name = str(state.get("name", "")).strip()
            raw_arguments = str(state.get("arguments", ""))
            if not name:
                raise _malformed_tool_call_error("Responses function_call name is missing")
            try:
                parsed_args = _parse_tool_call_arguments(raw_arguments)
            except ValueError as exc:
                raise ProviderStreamTerminalError(
                    message="Responses function_call arguments are not a JSON object",
                    status="failed",
                    reason="malformed_tool_arguments",
                    completion_reason="response_malformed_tool_arguments",
                    error_code="PROVIDER_TOOL_ARGUMENTS_MALFORMED",
                    provider=None,
                    provider_transport="responses",
                    model=str(request.model) if request.model is not None else None,
                ) from exc
            emitted_tool_calls.add(call_id)
            return ChatStreamEvent(
                type="tool_calls",
                tool_calls=[
                    ToolCall(
                        call_id=call_id,
                        name=name,
                        args=parsed_args,
                        raw_arguments=raw_arguments,
                    )
                ],
            )

        def _malformed_tool_call_error(message: str) -> ProviderStreamTerminalError:
            return ProviderStreamTerminalError(
                message=message,
                status="failed",
                reason="malformed_tool_call",
                completion_reason="response_malformed_tool_call",
                error_code="PROVIDER_TOOL_CALL_MALFORMED",
                provider=None,
                provider_transport="responses",
                model=str(request.model) if request.model is not None else None,
            )

        def _text_from_response_output_item(item: Dict[str, Any]) -> str:
            text = item.get("text") or item.get("output_text")
            if isinstance(text, str):
                return text
            content = item.get("content")
            if isinstance(content, list):
                chunks = []
                for part in content:
                    if isinstance(part, dict):
                        part_text = part.get("text")
                        if isinstance(part_text, str):
                            chunks.append(part_text)
                return "".join(chunks)
            return ""

        def _tail_text_to_emit(text: str) -> str:
            if not text:
                return ""
            if not emitted_text:
                return text
            if text.startswith(emitted_text):
                return text[len(emitted_text) :]
            if text == emitted_text or text in emitted_text:
                return ""
            return text

        fallback_to_non_stream = False
        emitted_downstream_event = False

        def _raise_partial_stream_terminal_error() -> None:
            raise ProviderStreamTerminalError(
                message="partial Responses stream failed before terminal event; non-stream fallback is unsafe",
                status="incomplete",
                reason="partial_stream_error",
                completion_reason="response_partial_stream_error",
                error_code="PROVIDER_STREAM_TERMINAL",
                provider=None,
                provider_transport="responses",
                model=str(request.model) if request.model is not None else None,
            )

        while True:
            stream = await _request_stream()
            try:
                async for event_name, data in stream:
                    if event_name == "error":
                        error = data if isinstance(data, BaseException) else RuntimeError(f"Agently requester error: {data!r}")
                        if request_data.stream and _is_responses_empty_stream_error(error):
                            if emitted_downstream_event or tool_states:
                                _raise_partial_stream_terminal_error()
                            requester, request_data = _new_requester_and_data(stream=False)
                            tool_states.clear()
                            emitted_tool_calls.clear()
                            fallback_to_non_stream = True
                            break
                        raise error
                    if not isinstance(data, str):
                        continue
                    raw = data.strip()
                    if not raw or raw in ("[DONE]", "DONE"):
                        continue
                    try:
                        loaded = json.loads(raw)
                    except Exception as exc:
                        log_suppressed_exception(
                            context="parse_responses_stream_json",
                            exc=exc,
                            extra={"raw_len": len(raw), "event": str(event_name)},
                        )
                        continue
                    if not isinstance(loaded, dict):
                        continue

                    payload_type = str(loaded.get("type") or event_name)
                    if payload_type in {"response.failed", "response.incomplete", "response.cancelled"}:
                        response_payload = loaded.get("response", loaded)
                        response = response_payload if isinstance(response_payload, dict) else {}
                        raise _provider_terminal_error_from_response(
                            payload_type=payload_type,
                            response=response,
                            request_model=request.model,
                        )

                    if payload_type == "response.output_text.delta":
                        emitted_downstream_event = True
                        delta = str(loaded.get("delta", ""))
                        emitted_text += delta
                        yield ChatStreamEvent(type="text_delta", text=delta)
                        continue

                    if payload_type == "response.output_item.added":
                        item = loaded.get("item")
                        if isinstance(item, dict) and item.get("type") == "function_call":
                            call_id = str(item.get("call_id", "")).strip()
                            if not call_id:
                                raise _malformed_tool_call_error("Responses function_call call_id is missing")
                            state = _state_for(call_id, output_index=loaded.get("output_index"))
                            if isinstance(item.get("name"), str):
                                state["name"] = item["name"]
                            if isinstance(item.get("arguments"), str):
                                state["arguments"] = item["arguments"]
                        continue

                    if payload_type == "response.function_call_arguments.delta":
                        call_id = str(loaded.get("call_id", "")).strip()
                        if not call_id:
                            raise _malformed_tool_call_error("Responses function_call call_id is missing")
                        state = _state_for(call_id, output_index=loaded.get("output_index"))
                        state["arguments"] = str(state.get("arguments", "")) + str(loaded.get("delta", ""))
                        continue

                    if payload_type == "response.function_call_arguments.done":
                        call_id = str(loaded.get("call_id", "")).strip()
                        if not call_id:
                            raise _malformed_tool_call_error("Responses function_call call_id is missing")
                        state = _state_for(call_id, output_index=loaded.get("output_index"))
                        if isinstance(loaded.get("arguments"), str):
                            state["arguments"] = loaded["arguments"]
                        event = _tool_event_from_state(state)
                        if event is not None:
                            emitted_downstream_event = True
                            yield event
                        continue

                    if payload_type == "response.output_item.done":
                        item = loaded.get("item")
                        if isinstance(item, dict) and item.get("type") == "function_call":
                            call_id = str(item.get("call_id", "")).strip()
                            if not call_id:
                                raise _malformed_tool_call_error("Responses function_call call_id is missing")
                            state = _state_for(call_id, output_index=loaded.get("output_index"))
                            if isinstance(item.get("name"), str):
                                state["name"] = item["name"]
                            if isinstance(item.get("arguments"), str):
                                state["arguments"] = item["arguments"]
                            event = _tool_event_from_state(state)
                            if event is not None:
                                emitted_downstream_event = True
                                yield event
                        continue

                    if payload_type == "response.completed":
                        response_payload = loaded.get("response", loaded)
                        response = response_payload if isinstance(response_payload, dict) else {}
                        response_status = str(response.get("status") or "completed")
                        if response_status != "completed":
                            terminal_type = (
                                "response.cancelled"
                                if response_status == "cancelled"
                                else "response.incomplete"
                                if response_status == "incomplete"
                                else "response.failed"
                            )
                            raise _provider_terminal_error_from_response(
                                payload_type=terminal_type,
                                response=response,
                                request_model=request.model,
                            )
                        for state in list(tool_states.values()):
                            event = _tool_event_from_state(state)
                            if event is not None:
                                emitted_downstream_event = True
                                yield event

                        output_text = response.get("output_text")
                        has_output_text = isinstance(output_text, str) and bool(output_text)
                        if has_output_text:
                            text_to_emit = output_text
                            if emitted_text:
                                text_to_emit = output_text[len(emitted_text) :] if output_text.startswith(emitted_text) else ""
                            if text_to_emit:
                                emitted_downstream_event = True
                                emitted_text += text_to_emit
                                yield ChatStreamEvent(type="text_delta", text=text_to_emit)
                        output = response.get("output")
                        if isinstance(output, list):
                            for item in output:
                                if not isinstance(item, dict):
                                    continue
                                item_type = item.get("type")
                                if item_type == "function_call":
                                    call_id = str(item.get("call_id", "")).strip()
                                    if not call_id:
                                        raise _malformed_tool_call_error("Responses function_call call_id is missing")
                                    state = _state_for(call_id)
                                    if isinstance(item.get("name"), str):
                                        state["name"] = item["name"]
                                    if isinstance(item.get("arguments"), str):
                                        state["arguments"] = item["arguments"]
                                    event = _tool_event_from_state(state)
                                    if event is not None:
                                        emitted_downstream_event = True
                                        yield event
                                elif item_type in {"message", "output_text"} and not has_output_text:
                                    text = _text_from_response_output_item(item)
                                    text_to_emit = _tail_text_to_emit(text)
                                    if text_to_emit:
                                        emitted_downstream_event = True
                                        emitted_text += text_to_emit
                                        yield ChatStreamEvent(type="text_delta", text=text_to_emit)

                        usage_payload = _normalize_usage_payload(
                            usage=response.get("usage"),
                            model=response.get("model") or request.model,
                            request_id=response.get("id"),
                            provider=response.get("provider"),
                            provider_transport="responses",
                            allow_metadata_only=True,
                        )
                        if usage_payload is not None and usage_sink is not None:
                            try:
                                usage_sink(dict(usage_payload))
                            except Exception as sink_exc:
                                log_suppressed_exception(
                                    context="usage_sink_callback",
                                    exc=sink_exc,
                                    extra={"source": "agently_responses_backend"},
                                )
                        usage = response.get("usage")
                        completed_usage = {
                            "input_tokens": _usage_int(usage.get("input_tokens")) if isinstance(usage, dict) else None,
                            "output_tokens": _usage_int(usage.get("output_tokens")) if isinstance(usage, dict) else None,
                            "total_tokens": _usage_int(usage.get("total_tokens")) if isinstance(usage, dict) else None,
                        }
                        completed_usage = {k: v for k, v in completed_usage.items() if v is not None}
                        finish_reason = "tool_calls" if emitted_tool_calls else "stop"
                        yield ChatStreamEvent(
                            type="completed",
                            finish_reason=finish_reason,
                            usage=completed_usage or None,
                            request_id=str(response.get("id")) if response.get("id") is not None else None,
                            provider=str(response.get("provider")) if response.get("provider") is not None else None,
                        )
                        return
            except BaseException as error:
                if request_data.stream and _is_responses_empty_stream_error(error):
                    if emitted_downstream_event or tool_states:
                        _raise_partial_stream_terminal_error()
                    requester, request_data = _new_requester_and_data(stream=False)
                    tool_states.clear()
                    emitted_tool_calls.clear()
                    fallback_to_non_stream = True
                else:
                    raise
            if fallback_to_non_stream:
                fallback_to_non_stream = False
                continue
            break

        for state in list(tool_states.values()):
            event = _tool_event_from_state(state)
            if event is not None:
                yield event
        raise ProviderStreamTerminalError(
            message="Responses stream ended without response terminal event",
            status="incomplete",
            reason="missing_terminal_event",
            completion_reason="response_stream_ended_without_terminal",
            error_code="PROVIDER_STREAM_TERMINAL",
            provider=None,
            provider_transport="responses",
            model=str(request.model) if request.model is not None else None,
        )


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


def build_openai_responses_compatible_requester_factory(*, agently_agent: Any) -> AgentlyRequesterFactory:
    """
    构造 Responses requester_factory（复用 Agently OpenAIResponsesCompatible builtins）。

    参数：
    - `agently_agent`：宿主提供的 Agently agent（需包含 `plugin_manager` 与 `settings`）。

    返回：
    - requester_factory：无参可调用对象，返回 OpenAIResponsesCompatible requester 实例。
    """

    from agently.core import Prompt
    from agently.builtins.plugins.ModelRequester.OpenAIResponsesCompatible import OpenAIResponsesCompatible

    plugin_manager = getattr(agently_agent, "plugin_manager", None)
    settings = getattr(agently_agent, "settings", None)
    if plugin_manager is None or settings is None:
        raise TypeError("agently_agent must provide .plugin_manager and .settings")

    def _factory() -> AgentlyRequester:
        """按当前 agently settings 构建一次 Responses requester。"""

        prompt = Prompt(plugin_manager=plugin_manager, parent_settings=settings, name="capability-runtime-responses-backend")
        prompt.set("input", "bridge")
        return OpenAIResponsesCompatible(prompt, settings)

    return _factory


def build_agently_requester_factory(
    *,
    agently_agent: Any,
    strategy: ProviderRequesterStrategy,
) -> AgentlyRequesterFactory:
    """
    按 RuntimeConfig.requester_strategy 选择 Agently requester。

    默认 `chat_completions` 走既有 OpenAICompatible；`responses` 显式 opt-in
    到 OpenAIResponsesCompatible。这里仅选择 requester，Responses stream 归一化在 Slice B 落地。
    """

    if strategy == "chat_completions":
        factory = build_openai_compatible_requester_factory(agently_agent=agently_agent)
        setattr(factory, "requester_strategy", strategy)
        return factory
    if strategy == "responses":
        factory = build_openai_responses_compatible_requester_factory(agently_agent=agently_agent)
        setattr(factory, "requester_strategy", strategy)
        return factory
    raise ValueError(f"unsupported agently requester strategy: {strategy!r}")


def build_provider_requester_factory(
    *,
    provider_agent: Any,
    strategy: ProviderRequesterStrategy,
) -> ProviderRequesterFactory:
    """
    Advanced adapter helper for hosts that already hold a provider-native agent.

    Regular OpenAI-compatible integrations should prefer
    `build_openai_provider_requester_factory()`, which accepts neutral transport
    settings and keeps provider-native agent construction inside this adapter.
    """

    return build_agently_requester_factory(agently_agent=provider_agent, strategy=strategy)


def build_openai_provider_requester_factory(
    *,
    base_url: str,
    transport_model: str,
    api_key: str,
    strategy: ProviderRequesterStrategy,
    allowed_hosts: Optional[Collection[str]] = None,
    allow_insecure_transport: bool = False,
) -> ProviderRequesterFactory:
    """
    Build a provider requester factory from OpenAI-compatible transport settings.

    This is the public bootstrap helper for examples and downstream integrations:
    callers pass neutral transport settings, while the adapter keeps provider-native
    agent construction inside the bridge boundary. `transport_model` is only the
    provider requester bootstrap fallback; the runtime request model still comes
    from AgentSpec.llm_config / the SDK ChatRequest model.
    """

    from agently import Agently  # type: ignore
    import os

    parsed = urlparse(base_url)
    if allowed_hosts is not None:
        normalized_hosts = {str(host).strip().lower() for host in allowed_hosts if str(host).strip()}
        host = (parsed.hostname or "").lower()
        if not normalized_hosts or host not in normalized_hosts:
            raise ValueError("OPENAI_BASE_URL host is not in the allowed_hosts trusted host list")
    allow_insecure = allow_insecure_transport or os.getenv("CAPRT_REAL_PROVIDER_ALLOW_INSECURE_TRANSPORT") == "1"
    if parsed.scheme.lower() != "https" and not allow_insecure:
        raise ValueError(
            "OPENAI_BASE_URL must use https; pass allow_insecure_transport=True or set "
            "CAPRT_REAL_PROVIDER_ALLOW_INSECURE_TRANSPORT=1 only for a controlled private provider."
        )

    settings_name = "OpenAIResponsesCompatible" if strategy == "responses" else "OpenAICompatible"
    agent = Agently.create_agent()
    agent.settings.set_settings(
        settings_name,
        {
            "base_url": base_url,
            "model": transport_model,
            "auth": api_key,
        },
    )
    return build_provider_requester_factory(provider_agent=agent, strategy=strategy)
