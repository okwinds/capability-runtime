"""WorkflowAdapter 单元测试。"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest

from capability_runtime.protocol.agent import AgentSpec
from capability_runtime.protocol.capability import (
    CapabilityKind,
    CapabilityRef,
    CapabilityResult,
    CapabilitySpec,
    CapabilityStatus,
)
from capability_runtime.protocol.context import CancellationToken, ExecutionContext
from capability_runtime.protocol.workflow import (
    ConditionalStep,
    InputMapping,
    LoopStep,
    ParallelStep,
    Step,
    WorkflowSpec,
)
from capability_runtime.types import NodeReport
from capability_runtime.runtime import Runtime
from capability_runtime.config import RuntimeConfig


def _make_agent(id: str) -> AgentSpec:
    return AgentSpec(
        base=CapabilitySpec(id=id, kind=CapabilityKind.AGENT, name=id),
    )


def _build_runtime(*, agents: list[AgentSpec], handler) -> Runtime:
    """
    构造 mock Runtime，并注册 AgentSpec 列表。

    说明：
    - Workflow 由 Runtime 内部 WorkflowEngine 负责执行（不需要在测试中显式注入）。
    - handler 可返回：
      - Any（将被包装为 CapabilityResult.SUCCESS.output）
      - CapabilityResult（将被 Runtime 直接透传）
    """

    rt = Runtime(RuntimeConfig(mode="mock", max_depth=10, mock_handler=handler))
    rt.register_many(list(agents))
    return rt


@pytest.mark.asyncio
async def test_sequential_steps():
    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-1", kind=CapabilityKind.WORKFLOW, name="seq"),
        steps=[
            Step(id="s1", capability=CapabilityRef(id="A")),
            Step(
                id="s2",
                capability=CapabilityRef(id="B"),
                input_mappings=[
                    InputMapping(source="step.s1.__agent__", target_field="from")
                ],
            ),
        ],
    )
    def handler(spec: AgentSpec, input_dict: Dict[str, Any]):
        return {**input_dict, "__agent__": spec.base.id}

    rt = _build_runtime(agents=[_make_agent("A"), _make_agent("B")], handler=handler)
    rt.register(wf)

    result = await rt.run("WF-1", input={"data": "hello"})
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output["s1"]["__agent__"] == "A"
    assert result.output["s2"]["from"] == "A"


@pytest.mark.asyncio
async def test_workflow_cancellation_integration_stops_at_step_boundary() -> None:
    """
    集成护栏（task 9.6）：workflow 在步骤边界感知 cancel_token，并返回 CANCELLED。

    语义：
    - 取消发生在 step1 执行中：step1 允许完成；
    - 下一步开始前检测到已取消：跳过 step2，并返回 error="execution cancelled"。
    """

    started = asyncio.Event()
    proceed = asyncio.Event()
    called_b = False

    async def handler(spec: AgentSpec, _input: Dict[str, Any], _ctx: ExecutionContext):
        nonlocal called_b
        if spec.base.id == "A":
            started.set()
            await proceed.wait()
            return {"ok": True, "agent": "A"}
        if spec.base.id == "B":
            called_b = True
            raise AssertionError("step B should not be executed after cancellation")
        return {"ok": True}

    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-CANCEL", kind=CapabilityKind.WORKFLOW, name="cancel"),
        steps=[
            Step(id="s1", capability=CapabilityRef(id="A")),
            Step(id="s2", capability=CapabilityRef(id="B")),
        ],
    )

    rt = _build_runtime(agents=[_make_agent("A"), _make_agent("B")], handler=handler)
    rt.register(wf)

    token = CancellationToken()
    ctx = ExecutionContext(run_id="r1", cancel_token=token)

    task = asyncio.create_task(rt.run("WF-CANCEL", context=ctx))
    await asyncio.wait_for(started.wait(), timeout=1.0)
    token.cancel()
    proceed.set()
    result = await asyncio.wait_for(task, timeout=1.0)

    assert called_b is False
    assert result.status == CapabilityStatus.CANCELLED
    assert result.error == "execution cancelled"


@pytest.mark.asyncio
async def test_loop_step():
    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-L", kind=CapabilityKind.WORKFLOW, name="loop"),
        steps=[
            Step(id="plan", capability=CapabilityRef(id="PLANNER")),
            LoopStep(
                id="loop",
                capability=CapabilityRef(id="WORKER"),
                iterate_over="step.plan.items",
                item_input_mappings=[
                    InputMapping(source="item.name", target_field="name"),
                ],
                max_iterations=10,
            ),
        ],
    )

    def handler(spec: AgentSpec, input_dict: Dict[str, Any]):
        if spec.base.id == "PLANNER":
            return {"items": [{"name": "A"}, {"name": "B"}, {"name": "C"}]}
        return {"processed": input_dict.get("name", "?")}

    rt = _build_runtime(agents=[_make_agent("PLANNER"), _make_agent("WORKER")], handler=handler)
    rt.register(wf)

    result = await rt.run("WF-L")
    assert result.status == CapabilityStatus.SUCCESS
    loop_output = result.output["loop"]
    assert len(loop_output) == 3


@pytest.mark.asyncio
async def test_loop_step_collect_as_injects_results_into_context_bag() -> None:
    """
    回归护栏：LoopStep.collect_as 不能是 no-op。

    期望：
    - loop 的结果仍写入 `step_outputs[loop_step_id]`（对外输出保持一致）；
    - 同时把同一结果注入到 workflow 级 context 的 bag overlay（key=collect_as），允许后续步骤用
      `context.<collect_as>` 引用。
    """

    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-L-CA", kind=CapabilityKind.WORKFLOW, name="loop-collect-as"),
        steps=[
            Step(id="plan", capability=CapabilityRef(id="PLANNER")),
            LoopStep(
                id="loop",
                capability=CapabilityRef(id="WORKER"),
                iterate_over="step.plan.items",
                item_input_mappings=[InputMapping(source="item.name", target_field="name")],
                collect_as="results",
            ),
            Step(
                id="summarize",
                capability=CapabilityRef(id="SUMMARIZER"),
                input_mappings=[InputMapping(source="context.results", target_field="results")],
            ),
        ],
        output_mappings=[InputMapping(source="step.summarize.summary", target_field="summary")],
    )

    def handler(spec: AgentSpec, input_dict: Dict[str, Any]):
        if spec.base.id == "PLANNER":
            return {"items": [{"name": "A"}, {"name": "B"}]}
        if spec.base.id == "WORKER":
            return {"processed": input_dict.get("name")}
        if spec.base.id == "SUMMARIZER":
            results = input_dict.get("results")
            if results is None:
                return CapabilityResult(status=CapabilityStatus.FAILED, error="missing results")
            return {"summary": f"n={len(results)}"}
        return {"ok": True}

    rt = _build_runtime(
        agents=[_make_agent("PLANNER"), _make_agent("WORKER"), _make_agent("SUMMARIZER")],
        handler=handler,
    )
    rt.register(wf)

    result = await rt.run("WF-L-CA")
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output == {"summary": "n=2"}


@pytest.mark.asyncio
async def test_parallel_step():
    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-P", kind=CapabilityKind.WORKFLOW, name="parallel"),
        steps=[
            ParallelStep(
                id="p1",
                branches=[
                    Step(id="b1", capability=CapabilityRef(id="A")),
                    Step(id="b2", capability=CapabilityRef(id="B")),
                ],
                join_strategy="all_success",
            ),
        ],
    )

    def handler(spec: AgentSpec, input_dict: Dict[str, Any]):
        return {**input_dict, "__agent__": spec.base.id}

    rt = _build_runtime(agents=[_make_agent("A"), _make_agent("B")], handler=handler)
    rt.register(wf)

    result = await rt.run("WF-P", input={"data": "test"})
    assert result.status == CapabilityStatus.SUCCESS
    assert len(result.output["p1"]) == 2
    # 并行分支的内部 step_id 不应污染顶层输出（否则分支细节泄露到外部契约）。
    assert "b1" not in result.output
    assert "b2" not in result.output


@pytest.mark.asyncio
async def test_parallel_step_context_bag_is_isolated_between_branches():
    """
    回归护栏：并行分支不应共享同一个 ExecutionContext（尤其是 bag/step_outputs），
    否则一个分支对 bag 的写入会泄露到另一个分支并导致非确定性行为。
    """

    async def handler(spec: AgentSpec, _input: Dict[str, Any], context):
        # bag 已改为不可变映射（MappingProxyType）：不应再用“写入 bag”来测试隔离。
        # 改为断言：每个并行分支都有独立的 __wf_branch_id。
        _ = _input
        bid = context.bag.get("__wf_branch_id")
        if spec.base.id in ("A", "B"):
            return {"branch_id": bid, "agent": spec.base.id}
        return {"ok": True}

    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-P-ISO", kind=CapabilityKind.WORKFLOW, name="parallel-iso"),
        steps=[
            ParallelStep(
                id="p1",
                branches=[
                    Step(id="b1", capability=CapabilityRef(id="A")),
                    Step(id="b2", capability=CapabilityRef(id="B")),
                ],
                join_strategy="all_success",
            ),
        ],
    )

    rt = _build_runtime(agents=[_make_agent("A"), _make_agent("B")], handler=handler)
    rt.register(wf)

    result = await rt.run("WF-P-ISO")
    assert result.status == CapabilityStatus.SUCCESS
    branches = result.output["p1"]
    assert isinstance(branches, list)
    assert {b.get("agent") for b in branches} == {"A", "B"}
    assert all(b.get("branch_id") for b in branches)
    assert len({b.get("branch_id") for b in branches}) == 2


@pytest.mark.asyncio
async def test_conditional_step():
    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-C", kind=CapabilityKind.WORKFLOW, name="cond"),
        steps=[
            Step(id="classify", capability=CapabilityRef(id="CLASSIFIER")),
            ConditionalStep(
                id="branch",
                condition_source="step.classify.category",
                branches={
                    "romance": Step(id="rom", capability=CapabilityRef(id="ROMANCE")),
                    "action": Step(id="act", capability=CapabilityRef(id="ACTION")),
                },
            ),
        ],
    )

    def handler(spec: AgentSpec, _input: Dict[str, Any]):
        if spec.base.id == "CLASSIFIER":
            return {"category": "romance"}
        return {"genre": spec.base.id}

    rt = _build_runtime(
        agents=[_make_agent("CLASSIFIER"), _make_agent("ROMANCE"), _make_agent("ACTION")],
        handler=handler,
    )
    rt.register(wf)

    result = await rt.run("WF-C")
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output["branch"]["genre"] == "ROMANCE"


@pytest.mark.asyncio
async def test_conditional_step_can_route_by_step_report_status():
    """
    回归护栏：多 Agent 编排应能基于控制面证据（例如 NodeReport.status）做路由，
    而不是解析自由文本输出。
    """

    def handler(spec: AgentSpec, _input: Dict[str, Any]):
        if spec.base.id == "CLASSIFIER":
            report = NodeReport(
                status="needs_approval",
                reason="approval_pending",
                completion_reason="run_cancelled",
                engine={"name": "skills-runtime-sdk-python", "module": "skills_runtime"},
                bridge={"name": "capability-runtime"},
                run_id="r1",
                events_path="wal.jsonl",
                activated_skills=[],
                tool_calls=[],
                artifacts=[],
                meta={},
            )
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"category": "romance"},
                report=report,
            )
        return {"genre": spec.base.id}

    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-C-REPORT", kind=CapabilityKind.WORKFLOW, name="cond-report"),
        steps=[
            Step(id="classify", capability=CapabilityRef(id="CLASSIFIER")),
            ConditionalStep(
                id="branch",
                condition_source="result.classify.report.status",
                branches={
                    "needs_approval": Step(id="rom", capability=CapabilityRef(id="ROMANCE")),
                    "success": Step(id="act", capability=CapabilityRef(id="ACTION")),
                },
            ),
        ],
        output_mappings=[
            InputMapping(source="step.rom.genre", target_field="genre"),
        ],
    )

    rt = _build_runtime(
        agents=[_make_agent("CLASSIFIER"), _make_agent("ROMANCE"), _make_agent("ACTION")],
        handler=handler,
    )
    rt.register(wf)

    result = await rt.run("WF-C-REPORT")
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output["genre"] == "ROMANCE"


@pytest.mark.asyncio
async def test_output_mappings():
    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-O", kind=CapabilityKind.WORKFLOW, name="output"),
        steps=[
            Step(id="s1", capability=CapabilityRef(id="A")),
        ],
        output_mappings=[
            InputMapping(source="step.s1.__agent__", target_field="agent_name"),
        ],
    )

    def handler(spec: AgentSpec, input_dict: Dict[str, Any]):
        return {**input_dict, "__agent__": spec.base.id}

    rt = _build_runtime(agents=[_make_agent("A")], handler=handler)
    rt.register(wf)

    result = await rt.run("WF-O", input={"x": 1})
    assert result.output == {"agent_name": "A"}


@pytest.mark.asyncio
async def test_step_failure_aborts_workflow():
    def handler(spec: AgentSpec, _input: Dict[str, Any]):
        if spec.base.id == "B":
            return CapabilityResult(status=CapabilityStatus.FAILED, error="B failed")
        return "ok"

    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-F", kind=CapabilityKind.WORKFLOW, name="fail"),
        steps=[
            Step(id="s1", capability=CapabilityRef(id="A")),
            Step(id="s2", capability=CapabilityRef(id="B")),
            Step(id="s3", capability=CapabilityRef(id="C")),  # 不应执行
        ],
    )

    rt = _build_runtime(agents=[_make_agent("A"), _make_agent("B"), _make_agent("C")], handler=handler)
    rt.register(wf)

    result = await rt.run("WF-F")
    assert result.status == CapabilityStatus.FAILED
    assert "B failed" in (result.error or "")


@pytest.mark.asyncio
async def test_step_pending_aborts_workflow() -> None:
    """
    回归护栏：Workflow 不应把 PENDING 当作 SUCCESS 继续执行后续步骤，
    否则 needs_approval/incomplete 等语义会被吞掉。
    """

    called = {"C": 0}

    def handler(spec: AgentSpec, _input: Dict[str, Any]):
        if spec.base.id == "B":
            return CapabilityResult(
                status=CapabilityStatus.PENDING,
                output=None,
                error=None,
                report=NodeReport(
                    status="needs_approval",
                    reason="approval_pending",
                    completion_reason="run_cancelled",
                    engine={"name": "skills-runtime-sdk-python", "module": "skills_runtime"},
                    bridge={"name": "capability-runtime"},
                    run_id="r1",
                    events_path="wal.jsonl",
                    activated_skills=[],
                    tool_calls=[],
                    artifacts=[],
                    meta={},
                ),
            )
        if spec.base.id == "C":
            called["C"] += 1
            return "ok"
        return "ok"

    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-PEND", kind=CapabilityKind.WORKFLOW, name="pend"),
        steps=[
            Step(id="s1", capability=CapabilityRef(id="A")),
            Step(id="s2", capability=CapabilityRef(id="B")),
            Step(id="s3", capability=CapabilityRef(id="C")),  # 不应执行
        ],
    )

    rt = _build_runtime(agents=[_make_agent("A"), _make_agent("B"), _make_agent("C")], handler=handler)
    rt.register(wf)

    result = await rt.run("WF-PEND")
    assert result.status == CapabilityStatus.PENDING
    assert called["C"] == 0


@pytest.mark.asyncio
async def test_iterate_over_not_list():
    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-X", kind=CapabilityKind.WORKFLOW, name="bad-loop"),
        steps=[
            LoopStep(
                id="loop",
                capability=CapabilityRef(id="A"),
                iterate_over="context.items",
                max_iterations=10,
            ),
        ],
    )
    def handler(spec: AgentSpec, input_dict: Dict[str, Any]):
        return {**input_dict, "__agent__": spec.base.id}

    rt = _build_runtime(agents=[_make_agent("A")], handler=handler)
    rt.register(wf)

    result = await rt.run("WF-X", input={"items": "not-a-list"})
    assert result.status == CapabilityStatus.FAILED
    assert "expected list" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_workflow_run_stream_emits_lightweight_events() -> None:
    """
    验收护栏：
    - Workflow 路径 run_stream 默认输出轻量事件字典；
    - 终态仍通过 CapabilityResult 返回。
    """

    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-STREAM", kind=CapabilityKind.WORKFLOW, name="stream"),
        steps=[
            Step(id="s1", capability=CapabilityRef(id="A")),
            Step(id="s2", capability=CapabilityRef(id="B")),
        ],
    )

    def handler(spec: AgentSpec, input_dict: Dict[str, Any]):
        return {**input_dict, "__agent__": spec.base.id}

    rt = _build_runtime(agents=[_make_agent("A"), _make_agent("B")], handler=handler)
    rt.register(wf)

    events: list[dict[str, Any]] = []
    terminal: CapabilityResult | None = None
    async for item in rt.run_stream("WF-STREAM", input={"topic": "t"}):
        if isinstance(item, CapabilityResult):
            terminal = item
        else:
            assert isinstance(item, dict)
            events.append(item)

    assert terminal is not None
    assert terminal.status == CapabilityStatus.SUCCESS
    assert [e["type"] for e in events] == [
        "workflow.started",
        "workflow.step.started",
        "workflow.step.finished",
        "workflow.step.started",
        "workflow.step.finished",
        "workflow.finished",
    ]
    assert [e.get("step_id") for e in events if e["type"] == "workflow.step.started"] == ["s1", "s2"]
    assert events[-1]["status"] == "success"


@pytest.mark.asyncio
async def test_workflow_run_stream_pending_propagates_and_stops_next_steps() -> None:
    """
    验收护栏：
    - 中间步骤返回 PENDING 时，workflow 终态必须为 PENDING；
    - 后续步骤不得继续执行；
    - completed 轻量事件状态应反映 pending。
    """

    called = {"C": 0}

    def handler(spec: AgentSpec, _input: Dict[str, Any]):
        if spec.base.id == "B":
            return CapabilityResult(
                status=CapabilityStatus.PENDING,
                report=NodeReport(
                    status="needs_approval",
                    reason="approval_pending",
                    completion_reason="run_cancelled",
                    engine={"name": "skills-runtime-sdk-python", "module": "skills_runtime"},
                    bridge={"name": "capability-runtime"},
                    run_id="r1",
                    events_path="wal.jsonl",
                    activated_skills=[],
                    tool_calls=[],
                    artifacts=[],
                    meta={},
                ),
            )
        if spec.base.id == "C":
            called["C"] += 1
        return {"ok": True}

    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-STREAM-PENDING", kind=CapabilityKind.WORKFLOW, name="stream-pending"),
        steps=[
            Step(id="s1", capability=CapabilityRef(id="A")),
            Step(id="s2", capability=CapabilityRef(id="B")),
            Step(id="s3", capability=CapabilityRef(id="C")),
        ],
    )

    rt = _build_runtime(agents=[_make_agent("A"), _make_agent("B"), _make_agent("C")], handler=handler)
    rt.register(wf)

    events: list[dict[str, Any]] = []
    terminal: CapabilityResult | None = None
    async for item in rt.run_stream("WF-STREAM-PENDING"):
        if isinstance(item, CapabilityResult):
            terminal = item
        else:
            assert isinstance(item, dict)
            events.append(item)

    assert terminal is not None
    assert terminal.status == CapabilityStatus.PENDING
    assert called["C"] == 0
    assert not any(e.get("step_id") == "s3" for e in events)
    assert events[-1]["type"] == "workflow.finished"
    assert events[-1]["status"] == "pending"
