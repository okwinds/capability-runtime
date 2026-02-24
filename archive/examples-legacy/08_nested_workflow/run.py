"""示例 08：Workflow 嵌套 Workflow（成功路径 + 深度护栏）。"""
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
    RuntimeConfig,
    Step,
    WorkflowAdapter,
    WorkflowSpec,
)


def pretty(data: Any) -> str:
    """将对象格式化为便于终端阅读的 JSON 文本。"""
    return json.dumps(data, ensure_ascii=False, indent=2)


class NestedDemoAgentAdapter:
    """用于嵌套工作流演示的离线 Agent 适配器。"""

    async def execute(
        self,
        *,
        spec: AgentSpec,
        input: dict[str, Any],
        context: ExecutionContext,
        runtime: CapabilityRuntime,
    ) -> CapabilityResult:
        """按 agent id 返回可预测输出，并携带 depth 便于观察调用层级。"""
        _ = runtime
        agent_id = spec.base.id

        if agent_id == "agent.sub_draft":
            topic = str(input.get("topic", "unknown"))
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"text": f"draft({topic})", "depth": context.depth},
            )

        if agent_id == "agent.sub_polish":
            text = str(input.get("text", ""))
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"text": f"polish({text})", "depth": context.depth},
            )

        if agent_id == "agent.publisher":
            payload = input.get("polish_payload", {})
            text = payload.get("text") if isinstance(payload, dict) else str(payload)
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"final": f"publish({text})", "depth": context.depth},
            )

        if agent_id == "agent.leaf":
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"leaf": True, "depth": context.depth},
            )

        return CapabilityResult(
            status=CapabilityStatus.FAILED,
            error=f"Unsupported agent id: {agent_id}",
        )


def build_success_runtime() -> CapabilityRuntime:
    """构建嵌套成功示例的运行时。"""
    runtime = CapabilityRuntime(config=RuntimeConfig(max_depth=10))
    runtime.set_adapter(CapabilityKind.AGENT, NestedDemoAgentAdapter())
    runtime.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())

    runtime.register_many(
        [
            AgentSpec(
                base=CapabilitySpec(
                    id="agent.sub_draft",
                    kind=CapabilityKind.AGENT,
                    name="Sub Draft Agent",
                )
            ),
            AgentSpec(
                base=CapabilitySpec(
                    id="agent.sub_polish",
                    kind=CapabilityKind.AGENT,
                    name="Sub Polish Agent",
                )
            ),
            AgentSpec(
                base=CapabilitySpec(
                    id="agent.publisher",
                    kind=CapabilityKind.AGENT,
                    name="Publisher Agent",
                )
            ),
            WorkflowSpec(
                base=CapabilitySpec(
                    id="workflow.sub",
                    kind=CapabilityKind.WORKFLOW,
                    name="Sub Workflow",
                ),
                steps=[
                    Step(
                        id="draft",
                        capability=CapabilityRef(id="agent.sub_draft"),
                        input_mappings=[
                            InputMapping(source="context.topic", target_field="topic")
                        ],
                    ),
                    Step(
                        id="polish",
                        capability=CapabilityRef(id="agent.sub_polish"),
                        input_mappings=[
                            InputMapping(source="previous.text", target_field="text")
                        ],
                    ),
                ],
            ),
            WorkflowSpec(
                base=CapabilitySpec(
                    id="workflow.main",
                    kind=CapabilityKind.WORKFLOW,
                    name="Main Workflow",
                ),
                steps=[
                    Step(
                        id="call_sub",
                        capability=CapabilityRef(id="workflow.sub"),
                        input_mappings=[
                            InputMapping(source="context.topic", target_field="topic")
                        ],
                    ),
                    Step(
                        id="publish",
                        capability=CapabilityRef(id="agent.publisher"),
                        input_mappings=[
                            InputMapping(
                                source="step.call_sub.polish",
                                target_field="polish_payload",
                            )
                        ],
                    ),
                ],
            ),
        ]
    )
    return runtime


def build_depth_limit_runtime() -> CapabilityRuntime:
    """构建 4 层 workflow 嵌套示例，用于触发 recursion_limit。"""
    runtime = CapabilityRuntime(config=RuntimeConfig(max_depth=3))
    runtime.set_adapter(CapabilityKind.AGENT, NestedDemoAgentAdapter())
    runtime.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())

    specs: list[Any] = [
        AgentSpec(
            base=CapabilitySpec(
                id="agent.leaf",
                kind=CapabilityKind.AGENT,
                name="Leaf Agent",
            )
        )
    ]
    for level in range(1, 5):
        target_id = f"workflow.depth.{level + 1}" if level < 4 else "agent.leaf"
        specs.append(
            WorkflowSpec(
                base=CapabilitySpec(
                    id=f"workflow.depth.{level}",
                    kind=CapabilityKind.WORKFLOW,
                    name=f"Depth Workflow {level}",
                ),
                steps=[Step(id="next", capability=CapabilityRef(id=target_id))],
            )
        )

    runtime.register_many(specs)
    return runtime


async def demo_nested_success() -> None:
    """演示主工作流调用子工作流的成功路径。"""
    runtime = build_success_runtime()
    missing = runtime.validate()
    if missing:
        raise RuntimeError(f"Missing capabilities: {missing}")

    result = await runtime.run(
        "workflow.main",
        input={"topic": "capability runtime launch"},
    )
    if result.status != CapabilityStatus.SUCCESS:
        raise RuntimeError(f"Nested success demo failed: {result.error}")

    print("=== 08 nested_workflow / success ===")
    print(f"status={result.status.value}")
    print("output:")
    print(pretty(result.output))


async def demo_nested_depth_limit() -> None:
    """演示超深嵌套命中 max_depth 并返回 recursion_limit。"""
    runtime = build_depth_limit_runtime()
    missing = runtime.validate()
    if missing:
        raise RuntimeError(f"Missing capabilities: {missing}")

    result = await runtime.run("workflow.depth.1")
    error_type = result.metadata.get("error_type")

    print("=== 08 nested_workflow / depth_limit ===")
    print(f"status={result.status.value}")
    print(f"error_type={error_type}")
    print(f"error={result.error}")

    if result.status != CapabilityStatus.FAILED:
        raise RuntimeError("Expected FAILED status for depth-limit demo.")
    if error_type != "recursion_limit":
        raise RuntimeError(
            f"Expected error_type='recursion_limit', got {error_type!r}."
        )


async def main() -> None:
    """依次运行嵌套成功与深度护栏两个示例。"""
    await demo_nested_success()
    await demo_nested_depth_limit()


if __name__ == "__main__":
    asyncio.run(main())
