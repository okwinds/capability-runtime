from __future__ import annotations

import pytest

from capability_runtime.ui_events.v1 import PathSegment, RuntimeEvent, StreamLevel


def test_path_segment_supports_optional_instance_fields_and_forbids_extra() -> None:
    seg = PathSegment(kind="workflow", id="wf_inst_1", instance_id="wf_inst_1", ref={"kind": "workflow", "id": "wf.x"})
    assert seg.kind == "workflow"
    assert seg.id == "wf_inst_1"
    assert seg.instance_id == "wf_inst_1"
    assert seg.ref == {"kind": "workflow", "id": "wf.x"}

    with pytest.raises(Exception):
        PathSegment(kind="workflow", id="wf_inst_1", extra_field="nope")  # type: ignore[call-arg]


def test_runtime_event_v1_accepts_repeated_kind_in_path_and_old_payload_shape() -> None:
    ev = RuntimeEvent(
        schema="capability-runtime.runtime_event.v1",
        type="node.started",
        run_id="r1",
        seq=1,
        ts_ms=1,
        level=StreamLevel.UI,
        path=[
            PathSegment(kind="workflow", id="outer_inst", instance_id="outer_inst", ref={"kind": "workflow", "id": "wf.outer"}),
            PathSegment(kind="workflow", id="inner_inst", instance_id="inner_inst", ref={"kind": "workflow", "id": "wf.inner"}),
        ],
        data={},
    )
    assert [s.kind for s in ev.path] == ["workflow", "workflow"]

    # 旧 payload：PathSegment 只有 kind/id 仍可解析（v1 加法演进）
    old_seg = PathSegment(kind="step", id="s1")
    assert old_seg.instance_id is None
    assert old_seg.ref is None
