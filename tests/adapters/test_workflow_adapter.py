"""WorkflowAdapter 单元测试。"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest

from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.protocol.capability import (
    CapabilityKind,
    CapabilityRef,
    CapabilityResult,
    CapabilitySpec,
    CapabilityStatus,
)
from agently_skills_runtime.protocol.workflow import (
    ConditionalStep,
    InputMapping,
    LoopStep,
    ParallelStep,
    Step,
    WorkflowSpec,
)
from agently_skills_runtime.types import NodeReportV2
from agently_skills_runtime.runtime import Runtime
from agently_skills_runtime.config import RuntimeConfig


def _make_agent(id: str) -> AgentSpec:
    return AgentSpec(
        base=CapabilitySpec(id=id, kind=CapabilityKind.AGENT, name=id),
    )


def _build_runtime(*, agents: list[AgentSpec], handler) -> Runtime:
    """
    构造 mock Runtime，并注册 AgentSpec 列表。

    说明：
    - WorkflowAdapter 由 Runtime 内部负责调用（不需要在测试中显式注入）。
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
    - 同时把同一结果写入 `context.bag[collect_as]`，允许后续步骤用 `context.<collect_as>` 引用。
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
        """
        用 parent_context.bag 做“可见层级”的写入，增强用例强度：
        - 若并行分支错误共享同一个 branch_context，B 将观察到 A 的写入；
        - 若隔离正确，B 不应看到 leak。
        """

        if spec.base.id == "A":
            assert context.parent_context is not None
            context.parent_context.bag["leak"] = "A"
            return {"ok": True}
        if spec.base.id == "B":
            await asyncio.sleep(0)
            assert context.parent_context is not None
            if "leak" in context.parent_context.bag:
                return CapabilityResult(status=CapabilityStatus.FAILED, error="context leak detected")
            return {"ok": True}
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
            report = NodeReportV2(
                status="needs_approval",
                reason="approval_pending",
                completion_reason="run_cancelled",
                engine={"name": "skills-runtime-sdk-python", "module": "agent_sdk"},
                bridge={"name": "agently-skills-runtime"},
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
                report=NodeReportV2(
                    status="needs_approval",
                    reason="approval_pending",
                    completion_reason="run_cancelled",
                    engine={"name": "skills-runtime-sdk-python", "module": "agent_sdk"},
                    bridge={"name": "agently-skills-runtime"},
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
