from __future__ import annotations

"""
Runtime UI Events：通用传输适配（JSON Lines / SSE 子集）。

定位：
- 不绑定任何 Web 框架；
- 只负责 framing（把 RuntimeEvent 转成可流式发送的文本 chunk）。
"""

import json

from .v1 import RuntimeEvent


def encode_json_line(ev: RuntimeEvent, *, prefix_data: bool = False) -> str:
    """
    将单条 RuntimeEvent 编码为可流式发送的文本。

    参数：
    - ev：RuntimeEvent
    - prefix_data：是否使用 `data: ` 前缀（SSE 子集兼容）

    返回：
    - JSONL：`<json>\\n`
    - SSE 子集：`data: <json>\\n\\n`
    """

    payload = json.dumps(ev.model_dump(by_alias=True), ensure_ascii=False, separators=(",", ":"))
    if prefix_data:
        return f"data: {payload}\n\n"
    return payload + "\n"

