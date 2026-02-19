from __future__ import annotations

import json

from agently_skills_web_backend.event_log import RunEventLog
from agently_skills_web_backend.models import RunEvent


def test_event_log_sse_stream_replays_and_closes():
    log = RunEventLog()
    log.append(RunEvent(ts="t1", run_id="r1", type="a", payload={"x": 1}))
    log.append(RunEvent(ts="t2", run_id="r1", type="b", payload={"x": 2}))
    log.close()

    items = list(log.sse_stream(start_index=0, heartbeat_sec=0.01))
    assert any("event: message" in s for s in items)
    assert any("event: done" in s for s in items)

    msgs = [s for s in items if "event: message" in s]
    assert len(msgs) >= 2

