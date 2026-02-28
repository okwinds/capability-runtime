"""
HistoryAssembler：从 TurnDelta 序列组装 `initial_history`（最小披露）。

约束（MVR）：
- 仅输出 `role in {"user","assistant"}` 的最小消息形态 `{role, content}`；
- tool 结果与敏感信息默认不进入 prompt（如需进入必须由宿主生成摘要后写入 user/assistant 文本）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .turn_delta import TurnDelta


class HistoryAssemblerConfig(BaseModel):
    """
    HistoryAssembler 配置。

    参数：
    - max_turns：最多回传多少个 turn（按时间顺序取末尾 N 个）
    - max_message_chars：单条 message 的最大字符数（截断兜底，避免 prompt 膨胀）
    """

    model_config = ConfigDict(extra="forbid")

    max_turns: int = Field(default=20, ge=0)
    max_message_chars: int = Field(default=8000, ge=1)


@dataclass(frozen=True)
class HistoryAssembler:
    """
    HistoryAssembler：将 TurnDelta[] 组装为 `initial_history`。

    说明：
    - 该类不读取 WAL，不推断工具行为；只消费宿主存储的 TurnDelta（真相源）。
    - TurnDelta.user_input 缺失时会跳过 user message（保守策略）。
    """

    config: HistoryAssemblerConfig = field(default_factory=HistoryAssemblerConfig)

    def build_initial_history(self, *, deltas: List[TurnDelta]) -> List[Dict[str, Any]]:
        """
        组装 `initial_history`（OpenAI wire messages 子集）。

        参数：
        - deltas：按时间顺序的 TurnDelta 列表（建议已按 created_at_ms 排序）

        返回：
        - `[{role, content}, ...]`，其中 role 仅包含 user/assistant
        """

        if self.config.max_turns <= 0 or not deltas:
            return []

        tail = deltas[-self.config.max_turns :]
        out: List[Dict[str, Any]] = []
        for d in tail:
            if d.user_input is not None:
                out.append({"role": "user", "content": self._truncate(d.user_input)})
            if d.final_output:
                out.append({"role": "assistant", "content": self._truncate(d.final_output)})
        return out

    def _truncate(self, text: str) -> str:
        """截断 message 内容（兜底）。"""

        s = str(text or "")
        n = self.config.max_message_chars
        return s if len(s) <= n else (s[: n - 3] + "...")
