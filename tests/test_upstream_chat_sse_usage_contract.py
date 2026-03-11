from __future__ import annotations

"""
升级护栏（skills-runtime-sdk==0.1.9）：
- 上游 `ChatCompletionsSseParser` 在 `finish_reason="stop"` 后允许等待 usage-only chunk /
  `[DONE]`，并把标准化 usage/request_id/provider 挂到最终 `completed` 事件。
- 本仓 bridge / reporting / UI metrics 依赖该事实；若上游回退为旧行为，升级必须被护栏拦住。
"""

from skills_runtime.llm.chat_sse import ChatCompletionsSseParser


def test_upstream_parser_emits_completed_with_usage_request_id_and_provider() -> None:
    parser = ChatCompletionsSseParser()

    events = parser.feed_data('{"id":"req_123","choices":[{"delta":{},"finish_reason":"stop"}]}')
    assert events == []

    events = parser.feed_data(
        '{"id":"req_123","usage":{"prompt_tokens":11,"completion_tokens":7,"total_tokens":18},"choices":[]}'
    )
    assert events == []

    events = parser.feed_data("[DONE]")
    assert [event.type for event in events] == ["completed"]

    completed = events[0]
    assert completed.finish_reason == "stop"
    assert completed.request_id == "req_123"
    assert completed.provider == "openai"
    assert completed.usage == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
    }
