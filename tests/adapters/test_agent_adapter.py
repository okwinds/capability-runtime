"""AgentAdapter 单元测试（以统一 Runtime + mock/bridge 语义为真相源）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from capability_runtime.config import RuntimeConfig
from capability_runtime.protocol.agent import AgentIOSchema, AgentSpec
from capability_runtime.protocol.capability import (
    CapabilityKind,
    CapabilityResult,
    CapabilitySpec,
    CapabilityStatus,
)
from capability_runtime.protocol.context import ExecutionContext
from capability_runtime.runtime import Runtime


def _mk_runtime(*, cfg: RuntimeConfig) -> Runtime:
    rt = Runtime(cfg)
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))
    return rt


@pytest.mark.asyncio
async def test_mock_handler_can_return_capability_result() -> None:
    def handler(_spec: AgentSpec, _input: Dict[str, Any]) -> CapabilityResult:
        return CapabilityResult(status=CapabilityStatus.PENDING, output={"needs": "approval"})

    rt = _mk_runtime(cfg=RuntimeConfig(mode="mock", mock_handler=handler))
    out = await rt.run("A", context=ExecutionContext(run_id="r1"))
    assert out.status == CapabilityStatus.PENDING
    assert out.output == {"needs": "approval"}


@pytest.mark.asyncio
async def test_mock_handler_can_be_async() -> None:
    async def handler(_spec: AgentSpec, input_dict: Dict[str, Any], _ctx: ExecutionContext) -> Dict[str, Any]:
        return {"ok": True, "x": input_dict.get("x")}

    rt = _mk_runtime(cfg=RuntimeConfig(mode="mock", mock_handler=handler))
    out = await rt.run("A", input={"x": 1}, context=ExecutionContext(run_id="r1"))
    assert out.status == CapabilityStatus.SUCCESS
    assert out.output["ok"] is True
    assert out.output["x"] == 1


def test_build_task_includes_output_schema_and_skills_mentions() -> None:
    rt = _mk_runtime(
        cfg=RuntimeConfig(
            mode="sdk_native",
            workspace_root=Path("."),
            preflight_mode="off",
            skills_config={
                "roots": [],
                "mode": "explicit",
                "max_auto": 3,
                "spaces": [
                    {
                        "id": "sp1",
                        "account": "acct",
                        "domain": "dm",
                        "sources": ["mem1"],
                        "enabled": True,
                    }
                ],
                "sources": [
                    {
                        "id": "mem1",
                        "type": "in-memory",
                        "options": {"namespace": "ns"},
                    }
                ],
                "injection": {"max_bytes": None},
            },
        )
    )

    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A", description="做一件事"),
        output_schema=AgentIOSchema(fields={"score": "int"}),
        skills=["topic-scorer"],
    )

    task = rt._agent_adapter._build_task(spec=spec, input={"x": 1})  # type: ignore[attr-defined]
    assert "## 任务" in task
    assert "做一件事" in task
    assert "## 输入" in task
    assert "## 输出要求" in task
    assert "score" in task
    assert "$[acct:dm].topic-scorer" in task


def test_build_task_prefers_skills_mention_map_when_provided() -> None:
    rt = _mk_runtime(cfg=RuntimeConfig(mode="sdk_native", workspace_root=Path("."), preflight_mode="off"))
    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
        skills=["s1"],
        skills_mention_map={"s1": "$[x:y].s1"},
    )
    task = rt._agent_adapter._build_task(spec=spec, input={})  # type: ignore[attr-defined]
    assert "$[x:y].s1" in task
