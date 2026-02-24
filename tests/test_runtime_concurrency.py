from __future__ import annotations

"""回归护栏：并发 run 必须隔离 per-run guards 等可变状态。"""

import asyncio
from typing import Any, Dict

import pytest

from agently_skills_runtime.config import RuntimeConfig
from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.protocol.capability import CapabilityKind, CapabilitySpec, CapabilityStatus
from agently_skills_runtime.protocol.context import ExecutionContext
from agently_skills_runtime.runtime import Runtime


@pytest.mark.asyncio
async def test_concurrent_runs_have_distinct_guards_instances() -> None:
    async def handler(_spec: AgentSpec, _input: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        guard_id = id(ctx.guards)
        await asyncio.sleep(0)
        return {"run_id": ctx.run_id, "guard_id": guard_id}

    rt = Runtime(RuntimeConfig(mode="mock", mock_handler=handler))
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))

    c1 = ExecutionContext(run_id="r1")
    c2 = ExecutionContext(run_id="r2")

    r1, r2 = await asyncio.gather(rt.run("A", context=c1), rt.run("A", context=c2))
    assert r1.status == CapabilityStatus.SUCCESS
    assert r2.status == CapabilityStatus.SUCCESS
    assert r1.output["run_id"] == "r1"
    assert r2.output["run_id"] == "r2"
    assert r1.output["guard_id"] != r2.output["guard_id"]

