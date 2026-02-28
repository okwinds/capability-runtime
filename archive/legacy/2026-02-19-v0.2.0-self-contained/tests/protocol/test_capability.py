from __future__ import annotations

from capability_runtime.protocol.capability import (
    CapabilityKind,
    CapabilityResult,
    CapabilitySpec,
    CapabilityStatus,
)


def test_capability_spec_constructible() -> None:
    spec = CapabilitySpec(id="x", kind=CapabilityKind.SKILL, name="X")
    assert spec.id == "x"
    assert spec.kind == CapabilityKind.SKILL
    assert spec.name == "X"


def test_capability_result_fields() -> None:
    res = CapabilityResult(status=CapabilityStatus.SUCCESS, output={"ok": True})
    assert res.status == CapabilityStatus.SUCCESS
    assert res.output == {"ok": True}
    assert res.error is None
    assert res.artifacts == []

