"""
Web approvals broker（同步阻塞接口）。

背景：
- SDK ToolRegistry 的 tool handler 是同步函数（见本仓 TriggerFlow tool 的约束说明）。
- 因此 approvals 必须提供同步阻塞的“请求→等待→决策”机制（fail-closed）。
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent_sdk.tools.protocol import HumanIOProvider

from .models import ApprovalPendingItem, RunEvent


@dataclass
class _PendingApproval:
    approval_id: str
    run_id: str
    call_id: str
    question: str
    choices: List[str]
    context: Dict[str, Any]
    created_at_epoch: float

    decided: bool = False
    decision: str = "deny"
    reason: str = ""
    _event: threading.Event = field(default_factory=threading.Event, repr=False)


class ApprovalBroker:
    """管理待审批项，并支持同步阻塞等待人类决策。"""

    def __init__(self, *, emit_event: Any) -> None:
        """
        参数：
        - emit_event：回调函数，用于向 run 的事件流写入 approval 相关事件（RunEvent）。
        """

        self._emit_event = emit_event
        self._lock = threading.Lock()
        self._items: Dict[str, _PendingApproval] = {}

    def list_pending(self) -> List[ApprovalPendingItem]:
        with self._lock:
            out: List[ApprovalPendingItem] = []
            for it in self._items.values():
                if it.decided:
                    continue
                out.append(
                    ApprovalPendingItem(
                        approval_id=it.approval_id,
                        run_id=it.run_id,
                        call_id=it.call_id,
                        question=it.question,
                        choices=list(it.choices),
                        context=dict(it.context),
                    )
                )
            return out

    def decide(self, *, approval_id: str, decision: str, reason: str = "") -> bool:
        """写入审批决定；返回是否命中一个 pending item。"""

        with self._lock:
            it = self._items.get(approval_id)
            if it is None:
                return False
            if it.decided:
                return True
            it.decided = True
            it.decision = (decision or "deny").strip().lower()
            it.reason = reason or ""
            it._event.set()

        self._emit_event(
            RunEvent(
                ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                run_id=it.run_id,
                type="approval_decided",
                payload={
                    "approval_id": it.approval_id,
                    "call_id": it.call_id,
                    "decision": it.decision,
                    "reason": it.reason,
                },
            )
        )
        return True

    def request_and_wait(
        self,
        *,
        run_id: str,
        call_id: str,
        question: str,
        choices: List[str],
        context: Dict[str, Any],
        timeout_ms: Optional[int],
    ) -> str:
        """
        创建 pending approval 并阻塞等待决策。

        返回：
        - choice 文本（例如 "approve" / "deny"）
        """

        approval_id = secrets.token_hex(16)
        item = _PendingApproval(
            approval_id=approval_id,
            run_id=run_id,
            call_id=call_id,
            question=question,
            choices=list(choices),
            context=dict(context),
            created_at_epoch=time.time(),
        )

        with self._lock:
            self._items[approval_id] = item

        self._emit_event(
            RunEvent(
                ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                run_id=run_id,
                type="approval_requested",
                payload={
                    "approval_id": approval_id,
                    "call_id": call_id,
                    "question": question,
                    "choices": list(choices),
                    "context": dict(context),
                },
            )
        )

        # fail-closed：超时或中断都默认 deny
        timeout_sec = None if timeout_ms is None else max(0.0, float(timeout_ms) / 1000.0)
        ok = item._event.wait(timeout=timeout_sec)
        if not ok:
            self.decide(approval_id=approval_id, decision="deny", reason="timeout")
        return item.decision


class WebHumanIOProvider(HumanIOProvider):
    """
    用于 SDK ToolRegistry 的同步人类交互接口。

    约束：
    - 该接口会阻塞线程；因此 run 必须在后台线程执行，避免阻塞 Web server 主循环。
    """

    def __init__(self, *, run_id: str, broker: ApprovalBroker) -> None:
        self._run_id = run_id
        self._broker = broker

    def request_human_input(
        self,
        *,
        call_id: str,
        question: str,
        choices: List[str],
        context: Dict[str, Any],
        timeout_ms: Optional[int],
    ) -> str:
        return self._broker.request_and_wait(
            run_id=self._run_id,
            call_id=call_id,
            question=question,
            choices=choices,
            context=context,
            timeout_ms=timeout_ms,
        )

