"""原型验证：OpenAI 兼容 LLM runner 与稳健 JSON 提取。"""
from __future__ import annotations

import json
from typing import Any, List, Optional

import httpx


def extract_json_payload(content: str) -> Any:
    """从 LLM 文本中尽可能提取 JSON，失败时返回原始字符串。"""
    text = content.strip()
    if not text:
        return ""

    parsed = _try_json_loads(text)
    if parsed is not None:
        return parsed

    fenced = _extract_fenced_json(text)
    if fenced is not None:
        return fenced

    candidate = _extract_first_balanced_json(text)
    if candidate is not None:
        parsed_candidate = _try_json_loads(candidate)
        if parsed_candidate is not None:
            return parsed_candidate

    return content


def _try_json_loads(text: str) -> Any:
    """尝试解析 JSON，失败返回 None。"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _extract_fenced_json(text: str) -> Any:
    """解析 ```json ... ``` 或 ``` ... ``` 代码块中的 JSON。"""
    marker = "```"
    start = text.find(marker)
    while start != -1:
        lang_end = text.find("\n", start + len(marker))
        if lang_end == -1:
            return None
        language = text[start + len(marker) : lang_end].strip().lower()
        end = text.find(marker, lang_end + 1)
        if end == -1:
            return None
        block = text[lang_end + 1 : end].strip()
        if language in {"", "json"}:
            parsed = _try_json_loads(block)
            if parsed is not None:
                return parsed
        start = text.find(marker, end + len(marker))
    return None


def _extract_first_balanced_json(text: str) -> Optional[str]:
    """从文本中提取首个平衡的 JSON 对象或数组字符串。"""
    start_index = -1
    opening = ""
    for idx, ch in enumerate(text):
        if ch in "[{":
            start_index = idx
            opening = ch
            break
    if start_index == -1:
        return None

    closing = "]" if opening == "[" else "}"
    depth = 0
    in_string = False
    escaped = False

    for idx in range(start_index, len(text)):
        ch = text[idx]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue

        if ch == opening:
            depth += 1
        elif ch == closing:
            depth -= 1
            if depth == 0:
                return text[start_index : idx + 1]

    return None


async def create_llm_runner(
    base_url: str,
    api_key: str,
    model: str,
    *,
    timeout: float = 60.0,
    temperature: float = 0.7,
):
    """创建 OpenAI 兼容 runner（签名匹配 AgentAdapter 要求）。"""

    async def runner(task: str, *, initial_history: Optional[List] = None) -> Any:
        """执行单轮请求并把文本输出尽力解析为 JSON。"""
        messages = []
        if initial_history:
            messages.extend(initial_history)
        messages.append({"role": "user", "content": task})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        content = _extract_content(data)
        if isinstance(content, str):
            return extract_json_payload(content)
        return content

    return runner


def _extract_content(response_json: dict) -> Any:
    """兼容不同 OpenAI 兼容返回结构，提取 message.content。"""
    choices = response_json.get("choices")
    if not isinstance(choices, list) or not choices:
        return response_json

    first = choices[0]
    if not isinstance(first, dict):
        return response_json

    message = first.get("message")
    if not isinstance(message, dict):
        return response_json

    content = message.get("content")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "\n".join(parts)
    return content if content is not None else response_json
