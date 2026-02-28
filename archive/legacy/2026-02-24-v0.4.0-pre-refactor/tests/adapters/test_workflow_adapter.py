"""WorkflowAdapter 单元测试。"""
from __future__ import annotations

import pytest
import asyncio

from capability_runtime.adapters.workflow_adapter import WorkflowAdapter
from capability_runtime.protocol.agent import AgentSpec
from capability_runtime.protocol.capability import (
    CapabilityKind,
    CapabilityRef,
    CapabilityResult,
    CapabilitySpec,
    CapabilityStatus,
)
from capability_runtime.protocol.workflow import (
    ConditionalStep,
    InputMapping,
    LoopStep,
    ParallelStep,
    Step,
    WorkflowSpec,
)
from capability_runtime.runtime.engine import CapabilityRuntime, RuntimeConfig
from capability_runtime.types import NodeReportV2


class EchoAdapter:
    """Mock adapter：输出 = 输入 + spec_id。"""

    async def execute(self, *, spec, input, context, runtime):
        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output={**input, "__agent__": spec.base.id},
        )


def _make_agent(id: str) -> AgentSpec:
    return AgentSpec(
        base=CapabilitySpec(id=id, kind=CapabilityKind.AGENT, name=id),
    )


def _build_runtime(agents, adapter=None):
    rt = CapabilityRuntime(config=RuntimeConfig(max_depth=10))
    a = adapter or EchoAdapter()
    rt.set_adapter(CapabilityKind.AGENT, a)
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    for agent in agents:
        rt.register(agent)
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
    rt = _build_runtime([_make_agent("A"), _make_agent("B")])
    rt.register(wf)

    result = await rt.run("WF-1", input={"data": "hello"})
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output["s1"]["__agent__"] == "A"
    assert result.output["s2"]["from"] == "A"


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

    class PlannerAdapter:
        async def execute(self, *, spec, input, context, runtime):
            if spec.base.id == "PLANNER":
                return CapabilityResult(
                    status=CapabilityStatus.SUCCESS,
                    output={"items": [{"name": "A"}, {"name": "B"}, {"name": "C"}]},
                )
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"processed": input.get("name", "?")},
            )

    rt = CapabilityRuntime(config=RuntimeConfig(max_depth=10))
    rt.set_adapter(CapabilityKind.AGENT, PlannerAdapter())
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    rt.register(_make_agent("PLANNER"))
    rt.register(_make_agent("WORKER"))
    rt.register(wf)

    result = await rt.run("WF-L")
    assert result.status == CapabilityStatus.SUCCESS
    loop_output = result.output["loop"]
    assert len(loop_output) == 3


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

    rt = _build_runtime([_make_agent("A"), _make_agent("B")])
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

    class BagMutatingAdapter:
        async def execute(self, *, spec, input, context, runtime):
            if spec.base.id == "A":
                context.bag["leak"] = "A"
                return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"ok": True})
            if spec.base.id == "B":
                # 让 A 先写入（若共享 context，B 将看到 leak）
                await asyncio.sleep(0)
                if "leak" in context.bag:
                    return CapabilityResult(status=CapabilityStatus.FAILED, error="context leak detected")
                return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"ok": True})
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"ok": True})

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

    rt = CapabilityRuntime(config=RuntimeConfig(max_depth=10))
    rt.set_adapter(CapabilityKind.AGENT, BagMutatingAdapter())
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    rt.register(_make_agent("A"))
    rt.register(_make_agent("B"))
    rt.register(wf)

    result = await rt.run("WF-P-ISO")
    assert result.status == CapabilityStatus.SUCCESS


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

    class ClassifyAdapter:
        async def execute(self, *, spec, input, context, runtime):
            if spec.base.id == "CLASSIFIER":
                return CapabilityResult(
                    status=CapabilityStatus.SUCCESS,
                    output={"category": "romance"},
                )
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"genre": spec.base.id},
            )

    rt = CapabilityRuntime(config=RuntimeConfig(max_depth=10))
    rt.set_adapter(CapabilityKind.AGENT, ClassifyAdapter())
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    for id in ["CLASSIFIER", "ROMANCE", "ACTION"]:
        rt.register(_make_agent(id))
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

    class ReportClassifierAdapter:
        async def execute(self, *, spec, input, context, runtime):
            _ = input
            _ = context
            _ = runtime
            if spec.base.id == "CLASSIFIER":
                report = NodeReportV2(
                    status="needs_approval",
                    reason="approval_pending",
                    completion_reason="run_cancelled",
                    engine={"name": "skills-runtime-sdk-python", "module": "agent_sdk"},
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
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"genre": spec.base.id},
            )

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

    rt = CapabilityRuntime(config=RuntimeConfig(max_depth=10))
    rt.set_adapter(CapabilityKind.AGENT, ReportClassifierAdapter())
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    for id in ["CLASSIFIER", "ROMANCE", "ACTION"]:
        rt.register(_make_agent(id))
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

    rt = _build_runtime([_make_agent("A")])
    rt.register(wf)

    result = await rt.run("WF-O", input={"x": 1})
    assert result.output == {"agent_name": "A"}


@pytest.mark.asyncio
async def test_step_failure_aborts_workflow():
    class FailOnB:
        async def execute(self, *, spec, input, context, runtime):
            if spec.base.id == "B":
                return CapabilityResult(status=CapabilityStatus.FAILED, error="B failed")
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output="ok")

    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-F", kind=CapabilityKind.WORKFLOW, name="fail"),
        steps=[
            Step(id="s1", capability=CapabilityRef(id="A")),
            Step(id="s2", capability=CapabilityRef(id="B")),
            Step(id="s3", capability=CapabilityRef(id="C")),  # 不应执行
        ],
    )

    rt = CapabilityRuntime()
    rt.set_adapter(CapabilityKind.AGENT, FailOnB())
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    for id in ["A", "B", "C"]:
        rt.register(_make_agent(id))
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

    class PendingOnB:
        async def execute(self, *, spec, input, context, runtime):
            if spec.base.id == "B":
                return CapabilityResult(
                    status=CapabilityStatus.PENDING,
                    output=None,
                    error=None,
                    report=NodeReportV2(
                        status="needs_approval",
                        reason="approval_pending",
                        completion_reason="run_cancelled",
                        engine={"name": "skills-runtime-sdk-python", "module": "agent_sdk"},
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
                return CapabilityResult(status=CapabilityStatus.SUCCESS, output="ok")
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output="ok")

    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-PEND", kind=CapabilityKind.WORKFLOW, name="pend"),
        steps=[
            Step(id="s1", capability=CapabilityRef(id="A")),
            Step(id="s2", capability=CapabilityRef(id="B")),
            Step(id="s3", capability=CapabilityRef(id="C")),  # 不应执行
        ],
    )

    rt = CapabilityRuntime()
    rt.set_adapter(CapabilityKind.AGENT, PendingOnB())
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    for id in ["A", "B", "C"]:
        rt.register(_make_agent(id))
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
    rt = _build_runtime([_make_agent("A")])
    rt.register(wf)

    result = await rt.run("WF-X", input={"items": "not-a-list"})
    assert result.status == CapabilityStatus.FAILED
    assert "expected list" in (result.error or "").lower()
