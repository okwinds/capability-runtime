from __future__ import annotations

from capability_runtime.ui_events.transport import encode_json_line
from capability_runtime.ui_events.v1 import PathSegment, RuntimeEvent, StreamLevel


def test_encode_json_line_jsonl_and_sse_subset() -> None:
    ev = RuntimeEvent(
        schema="capability-runtime.runtime_event.v1",
        type="heartbeat",
        run_id="r1",
        seq=1,
        ts_ms=1,
        level=StreamLevel.UI,
        path=[PathSegment(kind="run", id="r1")],
        data={},
        rid="1",
    )

    line = encode_json_line(ev, prefix_data=False)
    assert line.endswith("\n")
    assert line.startswith("{")

    sse = encode_json_line(ev, prefix_data=True)
    assert sse.startswith("data: ")
    assert sse.endswith("\n\n")

