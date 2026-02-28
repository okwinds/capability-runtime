from __future__ import annotations

"""
Runtime UI Events：断线续传（rid/after_id）的最小 in-memory store。

定位：
- 提供最小可复用能力：append + read_after（exclusive）+ 过期诊断；
- 不绑定任何 HTTP 框架或持久化实现；
- run 级别隔离由调用方保证（通常一个 store 对应一个 run）。
"""

from collections import deque
from dataclasses import dataclass
from typing import Deque, Iterable, Optional, Protocol

from .v1 import RuntimeEvent


class RuntimeEventStore(Protocol):
    """
    RuntimeEventStore：用于断线续传的最小 store 接口（可插拔）。

    约束：
    - `read_after` 为排他语义（exclusive：strictly after）
    - after_id 过期/不在窗口内时，建议抛出 `AfterIdExpiredError`（可诊断）
    """

    @property
    def min_rid(self) -> Optional[str]: ...

    @property
    def max_rid(self) -> Optional[str]: ...

    def append(self, ev: RuntimeEvent) -> None: ...

    def read_after(self, *, after_id: Optional[str]) -> Iterable[RuntimeEvent]: ...


@dataclass(frozen=True)
class AfterIdExpiredError(Exception):
    """
    after_id 不在可用窗口内（可能是裁剪过期，也可能是未知/非法游标）。

    字段：
    - after_id：请求的游标
    - min_rid/max_rid：当前窗口内的可用范围（用于诊断与提示客户端策略）
    """

    after_id: str
    min_rid: Optional[str]
    max_rid: Optional[str]

    def __str__(self) -> str:
        return f"after_id expired or not found: {self.after_id!r} (available: {self.min_rid!r}..{self.max_rid!r})"


class InMemoryRuntimeEventStore(RuntimeEventStore):
    """
    in-memory 事件存储（ring buffer）。

    约束：
    - `read_after` 为排他语义（exclusive：strictly after）
    - 当 after_id 不在窗口内时抛出 AfterIdExpiredError（可诊断）
    """

    def __init__(self, *, max_events: int = 10_000) -> None:
        if max_events <= 0:
            raise ValueError("max_events must be > 0")
        self._max_events = int(max_events)
        self._events: Deque[RuntimeEvent] = deque(maxlen=self._max_events)

    @property
    def min_rid(self) -> Optional[str]:
        if not self._events:
            return None
        return self._events[0].rid

    @property
    def max_rid(self) -> Optional[str]:
        if not self._events:
            return None
        return self._events[-1].rid

    def append(self, ev: RuntimeEvent) -> None:
        if ev.rid is None:
            raise ValueError("RuntimeEvent.rid is required for resume store")
        self._events.append(ev)

    def read_after(self, *, after_id: Optional[str]) -> Iterable[RuntimeEvent]:
        """
        读取 after_id 之后的事件（exclusive）。

        参数：
        - after_id：续传游标；None 表示从头读取当前窗口
        """

        if after_id is None:
            return list(self._events)
        if not self._events:
            return []

        idx = None
        for i, ev in enumerate(self._events):
            if ev.rid == after_id:
                idx = i
                break
        if idx is None:
            raise AfterIdExpiredError(after_id=str(after_id), min_rid=self.min_rid, max_rid=self.max_rid)
        return list(self._events)[idx + 1 :]
