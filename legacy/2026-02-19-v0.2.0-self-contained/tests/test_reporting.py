from __future__ import annotations

from agently_skills_runtime.reporting import ReportBuilder


def test_report_builder_builds_report() -> None:
    b = ReportBuilder(run_id="r1", capability_id="cap1")
    b.emit("step.started", {"id": "s1"})
    b.set_meta("k", "v")

    report = b.build()
    assert report.run_id == "r1"
    assert report.capability_id == "cap1"
    assert report.meta["k"] == "v"
    assert [e.name for e in report.events] == ["step.started"]

