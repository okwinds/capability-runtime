"""
TurnDelta：一次 turn 的“事实记录”（数据面 + 控制面 + 审计指针）。

说明：
- TurnDelta 的目标是让业务存储“可审计事实”，而不是被迫存储上游 messages 细节。
- TurnDelta 可用于生成下一轮的 `initial_history`（通过 HistoryAssembler），也可用于审计/回放（通过 events_path 指针）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from ..types import NodeReportV2


@runtime_checkable
class TurnDeltaRedactor(Protocol):
    """
    TurnDelta 脱敏策略接口（由宿主实现）。

    约束：
    - 该接口仅处理“用户/助手文本”的脱敏；tool 证据链脱敏由 SDK/Bridge 负责。
    - 默认实现不保证识别所有 secrets；宿主应按自身合规要求实现更强策略。
    """

    def redact_user_input(self, text: str) -> str:
        """
        脱敏 user_input。

        参数：
        - text：原始 user_input 文本

        返回：
        - 脱敏后的文本（可截断/替换/移除）
        """

        ...

    def redact_assistant_output(self, text: str) -> str:
        """
        脱敏 assistant_output（即 final_output）。

        参数：
        - text：原始 final_output 文本

        返回：
        - 脱敏后的文本
        """

        ...


@dataclass(frozen=True)
class TruncatingTurnDeltaRedactor:
    """
    默认脱敏器：仅做截断（避免过长内容进入存储/日志）。

    注意：该策略不做 secrets 识别，仅作为“最小兜底”。
    """

    max_chars: int = 2000

    def redact_user_input(self, text: str) -> str:
        """对 user_input 做截断脱敏。"""

        s = str(text or "")
        return s if len(s) <= self.max_chars else (s[: self.max_chars - 3] + "...")

    def redact_assistant_output(self, text: str) -> str:
        """对 assistant_output 做截断脱敏。"""

        s = str(text or "")
        return s if len(s) <= self.max_chars else (s[: self.max_chars - 3] + "...")


class TurnDelta(BaseModel):
    """
    TurnDelta（一次回合事实）。

    字段说明：
    - session_id/host_turn_id：由宿主生成，用于生命周期管理与追溯。
    - run_id：一次执行的 run 标识（推荐与 host_turn_id 一一映射）。
    - user_input：本回合用户输入（可选；若缺失则无法从 TurnDelta 组装回 user message）。
    - final_output：数据面输出（自由文本允许，但建议宿主按需脱敏）。
    - node_report：控制面强结构（NodeReport v2）。
    - events_path：WAL 路径指针（来自 SDK/Bridge；不得伪造）。
    - created_at_ms：宿主记录的本回合创建时间（用于排序与回放）；不作为安全证据源。
    """

    model_config = ConfigDict(extra="forbid")

    session_id: Optional[str] = None
    host_turn_id: Optional[str] = None
    run_id: Optional[str] = None

    user_input: Optional[str] = None
    final_output: str = ""

    node_report: NodeReportV2
    events_path: Optional[str] = None

    created_at_ms: int = Field(default_factory=lambda: int(time.time() * 1000))

    def redacted(self, *, redactor: TurnDeltaRedactor) -> "TurnDelta":
        """
        返回脱敏后的 TurnDelta（不修改原对象）。

        参数：
        - redactor：脱敏策略

        返回：
        - 新的 TurnDelta（user_input/final_output 经脱敏）
        """

        return TurnDelta(
            session_id=self.session_id,
            host_turn_id=self.host_turn_id,
            run_id=self.run_id,
            user_input=redactor.redact_user_input(self.user_input) if self.user_input is not None else None,
            final_output=redactor.redact_assistant_output(self.final_output),
            node_report=self.node_report,
            events_path=self.events_path,
            created_at_ms=self.created_at_ms,
        )

