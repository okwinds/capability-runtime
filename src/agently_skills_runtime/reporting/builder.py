"""
builder.py

ReportBuilder：对 ExecutionReport 的轻量构建器。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .report import ExecutionEvent, ExecutionReport


@dataclass
class ReportBuilder:
    """
    执行报告构建器。

    设计目的：
    - 给 runtime/adapters 提供一致的“事件写入入口”；
    - 保持 payload 形态自由（避免强绑业务 domain JSON）。

    参数：
    - `run_id`：执行 run_id
    - `capability_id`：根能力 ID
    """

    run_id: str
    capability_id: str
    _events: list[ExecutionEvent] = field(default_factory=list, init=False)
    _meta: dict[str, Any] = field(default_factory=dict, init=False)

    def emit(self, name: str, payload: Any = None) -> None:
        """
        追加一条事件。

        参数：
        - name：事件名
        - payload：事件载荷
        """

        self._events.append(ExecutionEvent(name=name, payload=payload))

    def set_meta(self, key: str, value: Any) -> None:
        """
        写入 meta 字段。

        参数：
        - key：键
        - value：值
        """

        self._meta[key] = value

    def build(self) -> ExecutionReport:
        """
        构建 ExecutionReport（拷贝当前 events/meta）。

        返回：
        - ExecutionReport
        """

        return ExecutionReport(
            run_id=self.run_id,
            capability_id=self.capability_id,
            events=list(self._events),
            meta=dict(self._meta),
        )

