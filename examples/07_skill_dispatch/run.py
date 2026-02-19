"""示例 07：通过 SkillSpec.dispatch_rules 触发能力调度。"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from agently_skills_runtime import (
    AgentAdapter,
    AgentSpec,
    CapabilityKind,
    CapabilityRef,
    CapabilityRuntime,
    CapabilitySpec,
    CapabilityStatus,
    RuntimeConfig,
    SkillAdapter,
    SkillDispatchRule,
    SkillSpec,
)


def pretty(data: Any) -> str:
    """将对象格式化为便于终端阅读的 JSON 文本。"""
    return json.dumps(data, ensure_ascii=False, indent=2)


async def offline_runner(task: str, *, initial_history: Optional[list] = None) -> dict[str, Any]:
    """离线 runner：返回分析任务摘要。"""
    _ = initial_history
    return {
        "analysis": "offline analyzer completed",
        "task_preview": task[:120],
        "task_length": len(task),
    }


def build_runtime() -> CapabilityRuntime:
    """构建运行时并注册 router skill 与 analyzer agent。"""
    runtime = CapabilityRuntime(config=RuntimeConfig())
    runtime.set_adapter(CapabilityKind.SKILL, SkillAdapter())
    runtime.set_adapter(CapabilityKind.AGENT, AgentAdapter(runner=offline_runner))

    runtime.register(
        SkillSpec(
            base=CapabilitySpec(
                id="skill.router",
                kind=CapabilityKind.SKILL,
                name="Router Skill",
                description="根据 context_bag 条件决定是否调度 analyzer。",
            ),
            source="Router content: 在 analyze=True 时调度 analyzer agent。",
            source_type="inline",
            dispatch_rules=[
                SkillDispatchRule(
                    condition="analyze",
                    target=CapabilityRef(id="agent.analyzer"),
                )
            ],
        )
    )
    runtime.register(
        AgentSpec(
            base=CapabilitySpec(
                id="agent.analyzer",
                kind=CapabilityKind.AGENT,
                name="Analyzer Agent",
                description="被 Skill 调度的离线分析 Agent。",
            )
        )
    )
    return runtime


def print_case(title: str, status: str, output: Any, dispatched: Any) -> None:
    """打印单次运行结果，聚焦 output 与 metadata.dispatched。"""
    print(title)
    print(f"status={status}")
    print("output:")
    print(pretty(output))
    print("metadata.dispatched:")
    print(pretty(dispatched))
    print("---")


async def main() -> None:
    """执行两次 Skill：一次不触发 dispatch，一次触发 dispatch。"""
    runtime = build_runtime()
    missing = runtime.validate()
    if missing:
        raise RuntimeError(f"Missing capabilities: {missing}")

    case_without_dispatch = await runtime.run(
        "skill.router",
        input={"task": "请检查本周运营周报并给出结论。"},
    )
    dispatched0 = case_without_dispatch.metadata.get("dispatched")
    print_case(
        "=== 07 skill_dispatch / case1: analyze not set ===",
        case_without_dispatch.status.value,
        case_without_dispatch.output,
        dispatched0,
    )
    if dispatched0:
        raise RuntimeError("Expected no dispatch when context_bag.analyze is absent.")

    case_with_dispatch = await runtime.run(
        "skill.router",
        input={"task": "请检查本周运营周报并给出结论。"},
        context_bag={"analyze": True},
    )
    dispatched1 = case_with_dispatch.metadata.get("dispatched", [])
    print_case(
        "=== 07 skill_dispatch / case2: analyze=True ===",
        case_with_dispatch.status.value,
        case_with_dispatch.output,
        dispatched1,
    )
    if case_with_dispatch.status != CapabilityStatus.SUCCESS:
        raise RuntimeError(f"Run failed: {case_with_dispatch.error}")
    if len(dispatched1) != 1:
        raise RuntimeError("Expected exactly one dispatched target when analyze=True.")


if __name__ == "__main__":
    asyncio.run(main())
