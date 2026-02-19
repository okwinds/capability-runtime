"""
report.py

ExecutionReport：能力执行的“报告载体”（最小可用形态）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now() -> datetime:
    """获取 UTC 时间戳（timezone-aware）。"""

    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ExecutionEvent:
    """
    单条执行事件（结构尽量通用，不绑定上游字段）。

    字段：
    - `ts`：事件发生时间（UTC）
    - `name`：事件名（例如 step.started / step.finished / adapter.call）
    - `payload`：事件载荷（应为可序列化对象；但本层不做强制）
    """

    name: str
    payload: Any = None
    ts: datetime = field(default_factory=_utc_now)


@dataclass
class ExecutionReport:
    """
    执行报告：用于聚合一次 run 的事件、元信息与可诊断数据。

    字段：
    - `run_id`：执行 run_id（ExecutionContext.run_id）
    - `capability_id`：根能力 ID
    - `events`：事件序列（按 append 顺序）
    - `started_at` / `finished_at`：时间戳（UTC）
    - `meta`：可选元信息（例如配置快照、上游校验结果等）
    """

    run_id: str
    capability_id: str
    events: list[ExecutionEvent] = field(default_factory=list)
    started_at: datetime = field(default_factory=_utc_now)
    finished_at: datetime | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def finish(self) -> None:
        """
        标记报告完成（写入 finished_at）。

        注意：该方法不会改变事件序列，仅记录时间戳。
        """

        self.finished_at = _utc_now()

