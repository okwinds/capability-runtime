from __future__ import annotations

import threading
import time

from agently_skills_web_backend.approvals import ApprovalBroker
from agently_skills_web_backend.models import RunEvent


def test_approval_broker_blocks_and_unblocks_and_emits_events():
    events: list[RunEvent] = []
    broker = ApprovalBroker(emit_event=lambda ev: events.append(ev))

    out: dict[str, str] = {}

    def worker():
        out["decision"] = broker.request_and_wait(
            run_id="run1",
            call_id="c1",
            question="Q",
            choices=["approve", "deny"],
            context={"k": "v"},
            timeout_ms=10_000,
        )

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    # 等待 pending 出现
    for _ in range(50):
        pending = broker.list_pending()
        if pending:
            break
        time.sleep(0.01)

    pending = broker.list_pending()
    assert len(pending) == 1
    approval_id = pending[0].approval_id

    assert broker.decide(approval_id=approval_id, decision="approve", reason="ok") is True
    t.join(timeout=2)
    assert out.get("decision") == "approve"

    types = [e.type for e in events]
    assert "approval_requested" in types
    assert "approval_decided" in types

