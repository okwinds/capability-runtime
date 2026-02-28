from __future__ import annotations

import pytest

from agently_skills_runtime.ui_events.store import AfterIdExpiredError, InMemoryRuntimeEventStore
from agently_skills_runtime.ui_events.v1 import RuntimeEvent, StreamLevel


def _mk(seq: int) -> RuntimeEvent:
    return RuntimeEvent(
        schema="agently-skills-runtime.runtime_event.v1",
        type="heartbeat",
        run_id="r1",
        seq=seq,
        ts_ms=seq,
        level=StreamLevel.UI,
        path=[],
        data={},
        rid=str(seq),
    )


def test_store_read_after_is_exclusive_and_expired_is_diagnostic() -> None:
    store = InMemoryRuntimeEventStore(max_events=3)
    store.append(_mk(1))
    store.append(_mk(2))
    store.append(_mk(3))

    got = list(store.read_after(after_id="2"))
    assert [e.rid for e in got] == ["3"]

    with pytest.raises(AfterIdExpiredError) as exc:
        list(store.read_after(after_id="0"))
    assert exc.value.min_rid == "1"
    assert exc.value.max_rid == "3"

