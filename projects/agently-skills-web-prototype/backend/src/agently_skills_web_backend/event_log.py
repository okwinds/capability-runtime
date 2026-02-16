"""
事件日志与 SSE 订阅。

设计目标：
- 允许多个 SSE 客户端订阅同一个 run 的事件流；
- 新订阅者先收到历史事件，再阻塞等待新事件；
- run 结束后自动 close，使订阅者能够退出（避免悬挂连接）。
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Iterable, Iterator, List, Optional

from .models import RunEvent


@dataclass(frozen=True)
class SseMessage:
    """SSE message（最小 envelope）。"""

    event: str
    data: str


def _to_sse_lines(msg: SseMessage) -> str:
    # 按 SSE 规范：每条消息以空行结束。
    return f"event: {msg.event}\ndata: {msg.data}\n\n"


class RunEventLog:
    """按 run 维度存储事件，并支持阻塞订阅。"""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._events: List[RunEvent] = []
        self._closed = False

    def append(self, ev: RunEvent) -> None:
        with self._cond:
            self._events.append(ev)
            self._cond.notify_all()

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    def snapshot(self) -> List[RunEvent]:
        with self._cond:
            return list(self._events)

    def sse_stream(self, *, start_index: int = 0, heartbeat_sec: float = 15.0) -> Iterator[str]:
        """
        生成 SSE 字符串流（sync generator）。

        参数：
        - start_index：历史回放起点
        - heartbeat_sec：无事件时发送心跳，避免代理/浏览器断链
        """

        idx = max(0, int(start_index))
        while True:
            with self._cond:
                has_new = idx < len(self._events)
                if not has_new and not self._closed:
                    self._cond.wait(timeout=float(heartbeat_sec))
                    has_new = idx < len(self._events)

                if has_new:
                    ev = self._events[idx]
                    idx += 1
                    payload = ev.model_dump()
                    yield _to_sse_lines(SseMessage(event="message", data=json.dumps(payload, ensure_ascii=False)))
                    continue

                if self._closed:
                    yield _to_sse_lines(SseMessage(event="done", data=json.dumps({"closed": True}, ensure_ascii=False)))
                    return

            # heartbeat（尽量不占用锁）
            yield _to_sse_lines(SseMessage(event="heartbeat", data=json.dumps({"ok": True}, ensure_ascii=False)))

