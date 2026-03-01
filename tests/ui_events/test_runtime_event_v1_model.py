from __future__ import annotations

import pytest
from pydantic import ValidationError

from capability_runtime.ui_events.v1 import Evidence, PathSegment, RuntimeEvent, StreamLevel


def test_runtime_event_v1_model_forbids_extra_and_dumps_schema_alias() -> None:
    ev = RuntimeEvent(
        schema="capability-runtime.runtime_event.v1",
        type="run.status",
        run_id="r1",
        seq=1,
        ts_ms=1,
        level=StreamLevel.UI,
        path=[PathSegment(kind="run", id="r1")],
        data={"status": "running"},
        evidence=Evidence(events_path="wal://r1"),
        rid="1",
    )

    dumped = ev.model_dump(by_alias=True)
    assert dumped["schema"] == "capability-runtime.runtime_event.v1"
    assert "schema_id" not in dumped

    with pytest.raises(ValidationError):
        RuntimeEvent(
            schema="capability-runtime.runtime_event.v1",
            type="run.status",
            run_id="r1",
            seq=1,
            ts_ms=1,
            level=StreamLevel.UI,
            path=[],
            data={},
            rid="1",
            extra_field="nope",  # type: ignore[call-arg]
        )

    with pytest.raises(ValidationError):
        PathSegment(kind="run", id="r1", extra=1)  # type: ignore[call-arg]
