"""AgentAdapter 单元测试。"""
from __future__ import annotations

import pytest

from agently_skills_runtime.adapters.agent_adapter import AgentAdapter
from agently_skills_runtime.protocol.agent import AgentIOSchema, AgentSpec
from agently_skills_runtime.protocol.capability import (
    CapabilityKind,
    CapabilitySpec,
    CapabilityStatus,
)
from agently_skills_runtime.protocol.context import ExecutionContext
from agently_skills_runtime.runtime.registry import CapabilityRegistry


class FakeRuntime:
    """模拟 CapabilityRuntime 的最小接口。"""

    def __init__(self):
        self.registry = CapabilityRegistry()


async def mock_runner(task: str, *, initial_history=None) -> str:
    """Mock runner 直接返回 task 文本。"""
    return f"output:{task[:50]}"


@pytest.mark.asyncio
async def test_basic_execution():
    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
    )
    adapter = AgentAdapter(runner=mock_runner)
    rt = FakeRuntime()
    ctx = ExecutionContext(run_id="r1")

    result = await adapter.execute(
        spec=spec,
        input={"task": "hello"},
        context=ctx,
        runtime=rt,
    )

    assert result.status == CapabilityStatus.SUCCESS
    assert "output:" in result.output
    assert "hello" in result.output


@pytest.mark.asyncio
async def test_no_runner():
    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
    )
    adapter = AgentAdapter(runner=None)
    rt = FakeRuntime()
    ctx = ExecutionContext(run_id="r1")

    result = await adapter.execute(spec=spec, input={}, context=ctx, runtime=rt)

    assert result.status == CapabilityStatus.FAILED
    assert "no runner" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_prompt_template():
    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
        prompt_template="设计角色：{name}",
    )

    captured = {}

    async def capture_runner(task, *, initial_history=None):
        captured["task"] = task
        return "result"

    adapter = AgentAdapter(runner=capture_runner)
    rt = FakeRuntime()
    ctx = ExecutionContext(run_id="r1")

    await adapter.execute(spec=spec, input={"name": "Alice"}, context=ctx, runtime=rt)
    assert "设计角色：Alice" in captured["task"]


@pytest.mark.asyncio
async def test_prompt_template_missing_key():
    """prompt_template format 缺字段时应回退为模板原文 + 输入 JSON。"""
    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
        prompt_template="设计角色：{name}",
    )

    captured = {}

    async def capture_runner(task, *, initial_history=None):
        captured["task"] = task
        return "result"

    adapter = AgentAdapter(runner=capture_runner)
    rt = FakeRuntime()
    ctx = ExecutionContext(run_id="r1")

    await adapter.execute(spec=spec, input={"task": "x"}, context=ctx, runtime=rt)
    assert "设计角色：" in captured["task"]
    assert "输入参数" in captured["task"]


@pytest.mark.asyncio
async def test_system_prompt_as_initial_history():
    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
        system_prompt="你是专家",
    )

    captured = {}

    async def capture_runner(task, *, initial_history=None):
        captured["initial_history"] = initial_history
        return "result"

    adapter = AgentAdapter(runner=capture_runner)
    rt = FakeRuntime()
    ctx = ExecutionContext(run_id="r1")

    await adapter.execute(spec=spec, input={"task": "x"}, context=ctx, runtime=rt)
    assert captured["initial_history"][0]["role"] == "system"
    assert captured["initial_history"][0]["content"] == "你是专家"

def test_agent_adapter_init_has_no_skill_content_loader_param() -> None:
    """方案2：AgentAdapter 不再支持 Skill 内容注入参数。"""
    with pytest.raises(TypeError):
        AgentAdapter(runner=mock_runner, skill_content_loader=lambda _s: "x")  # type: ignore[arg-type]


def test_agent_spec_has_no_skills_field() -> None:
    """方案2：AgentSpec 不再声明 skills 字段，避免读者误解本仓在自带 skills 引擎。"""
    with pytest.raises(TypeError):
        AgentSpec(  # type: ignore[call-arg]
            base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
            skills=["sk1"],
        )


@pytest.mark.asyncio
async def test_output_schema_hint():
    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
        output_schema=AgentIOSchema(fields={"score": "int", "analysis": "str"}),
    )

    captured = {}

    async def capture_runner(task, *, initial_history=None):
        captured["task"] = task
        return "result"

    adapter = AgentAdapter(runner=capture_runner)
    rt = FakeRuntime()
    ctx = ExecutionContext(run_id="r1")

    await adapter.execute(spec=spec, input={"task": "x"}, context=ctx, runtime=rt)
    assert "JSON" in captured["task"]
    assert "score" in captured["task"]


@pytest.mark.asyncio
async def test_runner_exception():
    async def bad_runner(task, *, initial_history=None):
        raise ConnectionError("network error")

    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
    )
    adapter = AgentAdapter(runner=bad_runner)
    rt = FakeRuntime()
    ctx = ExecutionContext(run_id="r1")

    result = await adapter.execute(spec=spec, input={}, context=ctx, runtime=rt)
    assert result.status == CapabilityStatus.FAILED
    assert "network error" in (result.error or "")


@pytest.mark.asyncio
async def test_wrap_node_result_v2():
    """测试兼容 NodeResultV2 格式。"""

    class FakeNodeReport:
        status = "success"
        reason = None
        meta = {"final_output": "the output"}

    class FakeNodeResult:
        final_output = "the output"
        node_report = FakeNodeReport()

    async def nr_runner(task, *, initial_history=None):
        return FakeNodeResult()

    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
    )
    adapter = AgentAdapter(runner=nr_runner)
    rt = FakeRuntime()
    ctx = ExecutionContext(run_id="r1")

    result = await adapter.execute(spec=spec, input={}, context=ctx, runtime=rt)
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output == "the output"
    assert result.report is not None


@pytest.mark.asyncio
async def test_wrap_node_result_v2_maps_needs_approval_to_pending() -> None:
    class FakeNodeReport:
        status = "needs_approval"
        reason = "approval_pending"
        meta = {"final_output": "ignored"}

    class FakeNodeResult:
        final_output = "the output"
        node_report = FakeNodeReport()

    async def nr_runner(task, *, initial_history=None):
        return FakeNodeResult()

    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
    )
    adapter = AgentAdapter(runner=nr_runner)
    rt = FakeRuntime()
    ctx = ExecutionContext(run_id="r1")

    result = await adapter.execute(spec=spec, input={}, context=ctx, runtime=rt)
    assert result.status == CapabilityStatus.PENDING
    assert result.error is None
    assert result.report is not None
    assert getattr(result.report, "status", None) == "needs_approval"


@pytest.mark.asyncio
async def test_wrap_node_result_v2_maps_incomplete_to_pending_by_default() -> None:
    class FakeNodeReport:
        status = "incomplete"
        reason = "budget_exceeded"
        meta = {"final_output": "ignored"}

    class FakeNodeResult:
        final_output = "the output"
        node_report = FakeNodeReport()

    async def nr_runner(task, *, initial_history=None):
        return FakeNodeResult()

    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
    )
    adapter = AgentAdapter(runner=nr_runner)
    rt = FakeRuntime()
    ctx = ExecutionContext(run_id="r1")

    result = await adapter.execute(spec=spec, input={}, context=ctx, runtime=rt)
    assert result.status == CapabilityStatus.PENDING
    assert result.error is None
    assert result.report is not None
    assert getattr(result.report, "status", None) == "incomplete"


@pytest.mark.asyncio
async def test_wrap_node_result_v2_maps_cancelled_to_cancelled() -> None:
    class FakeNodeReport:
        status = "incomplete"
        reason = "cancelled"
        meta = {"final_output": "ignored"}

    class FakeNodeResult:
        final_output = "the output"
        node_report = FakeNodeReport()

    async def nr_runner(task, *, initial_history=None):
        return FakeNodeResult()

    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
    )
    adapter = AgentAdapter(runner=nr_runner)
    rt = FakeRuntime()
    ctx = ExecutionContext(run_id="r1")

    result = await adapter.execute(spec=spec, input={}, context=ctx, runtime=rt)
    assert result.status == CapabilityStatus.CANCELLED
    assert result.error is None
    assert result.report is not None
    assert getattr(result.report, "reason", None) == "cancelled"
