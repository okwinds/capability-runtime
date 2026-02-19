"""示例 06：通过 SkillSpec.inject_to 自动注入 Skill 到 Agent。"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from agently_skills_runtime import (
    AgentAdapter,
    AgentSpec,
    CapabilityKind,
    CapabilityRuntime,
    CapabilitySpec,
    CapabilityStatus,
    RuntimeConfig,
    SkillSpec,
)

INJECTED_MARKER = "写作守则：先给结构，再给细节。"


def pretty(data: Any) -> str:
    """将对象格式化为便于终端阅读的 JSON 文本。"""
    return json.dumps(data, ensure_ascii=False, indent=2)


async def offline_runner(task: str, *, initial_history: Optional[list] = None) -> dict[str, Any]:
    """离线 runner：返回 task 摘要，并标记是否命中注入内容。"""
    _ = initial_history
    return {
        "task_preview": task[:200],
        "task_length": len(task),
        "contains_injected_skill": INJECTED_MARKER in task,
    }


def build_runtime() -> CapabilityRuntime:
    """构建示例运行时并注册 Skill/Agent。"""
    runtime = CapabilityRuntime(config=RuntimeConfig())
    runtime.set_adapter(CapabilityKind.AGENT, AgentAdapter(runner=offline_runner))

    runtime.register(
        SkillSpec(
            base=CapabilitySpec(
                id="skill.writer.guide",
                kind=CapabilityKind.SKILL,
                name="Writer Guide",
                description="注入到 writer agent 的写作技能。",
            ),
            source=INJECTED_MARKER + "\n输出前先给大纲，再展开关键点。",
            source_type="inline",
            inject_to=["agent.writer"],
        )
    )

    runtime.register(
        AgentSpec(
            base=CapabilitySpec(
                id="agent.writer",
                kind=CapabilityKind.AGENT,
                name="Writer Agent",
                description="离线 writer agent，用于验证 skill 注入。",
            ),
            skills=[],
            prompt_template="请完成写作任务：{task}",
        )
    )
    return runtime


async def main() -> None:
    """运行示例并打印注入验证结果。"""
    runtime = build_runtime()
    missing = runtime.validate()
    if missing:
        raise RuntimeError(f"Missing capabilities: {missing}")

    result = await runtime.run(
        "agent.writer",
        input={"task": "撰写一段产品更新说明，突出价值与行动项。"},
    )
    if result.status != CapabilityStatus.SUCCESS:
        raise RuntimeError(f"Run failed: {result.error}")
    if not result.output.get("contains_injected_skill"):
        raise RuntimeError("Expected injected skill content not found in task.")

    print("=== 06 skill_injection ===")
    print(f"status={result.status.value}")
    print(pretty(result.output))


if __name__ == "__main__":
    asyncio.run(main())
