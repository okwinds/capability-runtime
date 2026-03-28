"""
Runtime UI Events：断线续传（rid/after_id）的最小 in-memory store。

定位：
- 提供最小可复用能力：append + read_after（exclusive）+ 过期诊断；
- 不绑定任何 HTTP 框架或持久化实现；
- run 级别隔离由调用方保证（通常一个 store 对应一个 run）。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import threading
from typing import Deque, Dict, Iterable, Optional, Protocol

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
        self._rid_to_pos: Dict[str, int] = {}
        self._start_pos = 0
        self._lock = threading.Lock()

    @property
    def min_rid(self) -> Optional[str]:
        with self._lock:
            if not self._events:
                return None
            return self._events[0].rid

    @property
    def max_rid(self) -> Optional[str]:
        with self._lock:
            if not self._events:
                return None
            return self._events[-1].rid

    def append(self, ev: RuntimeEvent) -> None:
        if ev.rid is None:
            raise ValueError("RuntimeEvent.rid is required for resume store")
        with self._lock:
            if len(self._events) == self._max_events:
                evicted = self._events.popleft()
                if evicted.rid is not None:
                    self._rid_to_pos.pop(evicted.rid, None)
                self._start_pos += 1
            pos = self._start_pos + len(self._events)
            self._events.append(ev)
            self._rid_to_pos[ev.rid] = pos

    def read_after(self, *, after_id: Optional[str]) -> Iterable[RuntimeEvent]:
        """
        读取 after_id 之后的事件（exclusive）。

        参数：
        - after_id：续传游标；None 表示从头读取当前窗口
        """

        with self._lock:
            snapshot = list(self._events)
            min_rid = snapshot[0].rid if snapshot else None
            max_rid = snapshot[-1].rid if snapshot else None
            if after_id is None:
                return snapshot
            if not snapshot:
                return []

            pos = self._rid_to_pos.get(str(after_id))
            if pos is None:
                raise AfterIdExpiredError(after_id=str(after_id), min_rid=min_rid, max_rid=max_rid)

            idx = pos - self._start_pos
            if idx < 0 or idx >= len(snapshot):
                raise AfterIdExpiredError(after_id=str(after_id), min_rid=min_rid, max_rid=max_rid)
            return snapshot[idx + 1 :]
