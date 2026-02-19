"""示例 04：使用 ParallelStep 分支的并行工作流。"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from agently_skills_runtime import (
    AgentSpec,
    CapabilityKind,
    CapabilityRef,
    CapabilityResult,
    CapabilityRuntime,
    CapabilitySpec,
    CapabilityStatus,
    ExecutionContext,
    InputMapping,
    ParallelStep,
    RuntimeConfig,
    Step,
    WorkflowAdapter,
    WorkflowSpec,
)


class ParallelDemoAgentAdapter:
    """用于并行工作流示例的 mock Agent 适配器。"""

    async def execute(
        self,
        *,
        spec: AgentSpec,
        input: dict[str, Any],
        context: ExecutionContext,
        runtime: CapabilityRuntime,
    ) -> CapabilityResult:
        """为各分支分析器与汇总器返回可预测输出。"""
        _ = context
        _ = runtime
        agent_id = spec.base.id

        if agent_id == "agent.analyzer_alpha":
            await asyncio.sleep(0.05)
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"analysis": f"alpha view on {input.get('data')}"},
            )

        if agent_id == "agent.analyzer_beta":
            await asyncio.sleep(0.03)
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"analysis": f"beta view on {input.get('data')}"},
            )

        if agent_id == "agent.analyzer_gamma":
            await asyncio.sleep(0.01)
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"analysis": f"gamma view on {input.get('data')}"},
            )

        if agent_id == "agent.synthesizer":
            alpha = str(input.get("alpha", ""))
            beta = str(input.get("beta", ""))
            gamma = str(input.get("gamma", ""))
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={
                    "report": f"SYNTHESIS: {alpha} | {beta} | {gamma}",
                },
            )

        return CapabilityResult(
            status=CapabilityStatus.FAILED,
            error=f"Unsupported agent id: {agent_id}",
        )


def pretty(data: Any) -> str:
    """将 JSON 输出格式化为便于终端阅读的文本。"""
    return json.dumps(data, ensure_ascii=False, indent=2)


def build_agent(agent_id: str, name: str) -> AgentSpec:
    """根据 id 与名称构建最小化的 Agent 规格。"""
    return AgentSpec(
        base=CapabilitySpec(
            id=agent_id,
            kind=CapabilityKind.AGENT,
            name=name,
            description=f"Offline mock agent: {name}",
        )
    )


def build_workflow() -> WorkflowSpec:
    """构建并行工作流，并在下游执行汇总步骤。"""
    return WorkflowSpec(
        base=CapabilitySpec(
            id="workflow.parallel.demo",
            kind=CapabilityKind.WORKFLOW,
            name="Parallel Workflow Demo",
            description="ParallelStep demo",
        ),
        steps=[
            ParallelStep(
                id="parallel_analysis",
                branches=[
                    Step(
                        id="alpha",
                        capability=CapabilityRef(id="agent.analyzer_alpha"),
                        input_mappings=[
                            InputMapping(source="context.data", target_field="data")
                        ],
                    ),
                    Step(
                        id="beta",
                        capability=CapabilityRef(id="agent.analyzer_beta"),
                        input_mappings=[
                            InputMapping(source="context.data", target_field="data")
                        ],
                    ),
                    Step(
                        id="gamma",
                        capability=CapabilityRef(id="agent.analyzer_gamma"),
                        input_mappings=[
                            InputMapping(source="context.data", target_field="data")
                        ],
                    ),
                ],
                join_strategy="all_success",
            ),
            Step(
                id="synthesize",
                capability=CapabilityRef(id="agent.synthesizer"),
                input_mappings=[
                    InputMapping(source="step.alpha.analysis", target_field="alpha"),
                    InputMapping(source="step.beta.analysis", target_field="beta"),
                    InputMapping(source="step.gamma.analysis", target_field="gamma"),
                ],
            ),
        ],
    )


async def main() -> None:
    """执行并行工作流并打印分支输出与汇总结果。"""
    runtime = CapabilityRuntime(config=RuntimeConfig())
    runtime.set_adapter(CapabilityKind.AGENT, ParallelDemoAgentAdapter())
    runtime.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())

    runtime.register_many(
        [
            build_agent("agent.analyzer_alpha", "Analyzer Alpha"),
            build_agent("agent.analyzer_beta", "Analyzer Beta"),
            build_agent("agent.analyzer_gamma", "Analyzer Gamma"),
            build_agent("agent.synthesizer", "Synthesizer"),
            build_workflow(),
        ]
    )

    missing = runtime.validate()
    if missing:
        raise RuntimeError(f"Missing capabilities: {missing}")

    result = await runtime.run(
        "workflow.parallel.demo",
        input={"data": "customer feedback set"},
    )
    if result.status != CapabilityStatus.SUCCESS:
        raise RuntimeError(f"Workflow failed: {result.error}")

    print("=== 04 workflow_parallel ===")
    print(f"workflow.status={result.status.value}")
    print("[alpha]")
    print(pretty(result.output["alpha"]))
    print("[beta]")
    print(pretty(result.output["beta"]))
    print("[gamma]")
    print(pretty(result.output["gamma"]))
    print("[parallel_analysis aggregate]")
    print(pretty(result.output["parallel_analysis"]))
    print("[synthesize]")
    print(pretty(result.output["synthesize"]))


if __name__ == "__main__":
    asyncio.run(main())
