from __future__ import annotations

"""CapabilitySpec / CapabilityResult 单元测试。"""

from agently_skills_runtime.protocol.capability import (
    CapabilityKind,
    CapabilityRef,
    CapabilityResult,
    CapabilitySpec,
    CapabilityStatus,
)


def test_capability_kind_values():
    assert CapabilityKind.AGENT == "agent"
    assert CapabilityKind.WORKFLOW == "workflow"


def test_capability_spec_construction():
    spec = CapabilitySpec(
        id="MA-013",
        kind=CapabilityKind.AGENT,
        name="单角色设计师",
        description="设计单个角色",
        version="1.0.0",
        tags=["TP2", "人物"],
        metadata={"author": "test"},
    )
    assert spec.id == "MA-013"
    assert spec.kind == CapabilityKind.AGENT
    assert spec.name == "单角色设计师"
    assert spec.version == "1.0.0"
    assert "TP2" in spec.tags
    assert spec.metadata["author"] == "test"


def test_capability_spec_defaults():
    spec = CapabilitySpec(id="x", kind=CapabilityKind.AGENT, name="x")
    assert spec.description == ""
    assert spec.version == "0.1.0"
    assert spec.tags == []
    assert spec.metadata == {}


def test_capability_ref():
    ref = CapabilityRef(id="MA-013", kind=CapabilityKind.AGENT)
    assert ref.id == "MA-013"
    assert ref.kind == CapabilityKind.AGENT

    ref_no_kind = CapabilityRef(id="WF-001")
    assert ref_no_kind.kind is None


def test_capability_status_values():
    assert CapabilityStatus.PENDING == "pending"
    assert CapabilityStatus.SUCCESS == "success"
    assert CapabilityStatus.FAILED == "failed"


def test_capability_result_success():
    result = CapabilityResult(
        status=CapabilityStatus.SUCCESS,
        output={"score": 85},
        duration_ms=1234.5,
    )
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output["score"] == 85
    assert result.error is None
    assert result.artifacts == []
    assert result.duration_ms == 1234.5


def test_capability_result_failed():
    result = CapabilityResult(
        status=CapabilityStatus.FAILED,
        error="timeout",
        metadata={"retry_count": 3},
    )
    assert result.status == CapabilityStatus.FAILED
    assert result.error == "timeout"
    assert result.metadata["retry_count"] == 3
