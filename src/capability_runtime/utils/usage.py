"""
Usage 提取工具：从 LLM usage payload 中提取标准化指标。

兼容：
- 本仓规范字段：`input_tokens/output_tokens/total_tokens`
- OpenAI 风格字段：`prompt_tokens/completion_tokens/total_tokens`
- provider metadata：`request_id/id/provider`
- 可选嵌套：`payload["usage"]`
"""

from __future__ import annotations

from typing import Any, Dict, Optional


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


def _usage_text(value: Any) -> Optional[str]:
    """把 provider metadata 字符串归一为空值安全的文本。"""

    return value.strip() if isinstance(value, str) and value.strip() else None


def extract_usage_metrics(payload: Any) -> Dict[str, Optional[Any]]:
    """
    从 `llm_usage` payload 中提取 usage 摘要。

    参数：
    - payload：AgentEvent.payload 或类似结构

    返回：
    - dict 包含 model/input_tokens/output_tokens/total_tokens/request_id/provider
    """

    if not isinstance(payload, dict):
        return {
            "model": None,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "request_id": None,
            "provider": None,
        }

    usage_raw = payload.get("usage")
    usage_dict: Dict[str, Any] = usage_raw if isinstance(usage_raw, dict) else payload
    model_text = _usage_text(payload.get("model")) or _usage_text(usage_dict.get("model"))
    request_id = (
        _usage_text(payload.get("request_id"))
        or _usage_text(payload.get("id"))
        or _usage_text(usage_dict.get("request_id"))
        or _usage_text(usage_dict.get("id"))
    )
    provider = _usage_text(payload.get("provider")) or _usage_text(usage_dict.get("provider"))

    input_tokens = _usage_int(usage_dict.get("input_tokens"))
    if input_tokens is None:
        input_tokens = _usage_int(usage_dict.get("prompt_tokens"))

    output_tokens = _usage_int(usage_dict.get("output_tokens"))
    if output_tokens is None:
        output_tokens = _usage_int(usage_dict.get("completion_tokens"))

    total_tokens = _usage_int(usage_dict.get("total_tokens"))

    return {
        "model": model_text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "request_id": request_id,
        "provider": provider,
    }
