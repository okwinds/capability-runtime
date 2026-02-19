from __future__ import annotations

import asyncio

from agently_skills_runtime import (
    CapabilityKind,
    CapabilityRuntime,
    CapabilitySpec,
    RuntimeConfig,
    SkillAdapter,
    SkillSpec,
)


async def main() -> None:
    """
    30 秒体验：
    - 声明一个 SkillSpec（inline 内容）
    - 注册到 CapabilityRuntime
    - 执行并打印结果
    """

    rt = CapabilityRuntime(config=RuntimeConfig())
    rt.set_adapter(CapabilityKind.SKILL, SkillAdapter())

    rt.register(
        SkillSpec(
            base=CapabilitySpec(
                id="skill.hello",
                kind=CapabilityKind.SKILL,
                name="Hello Skill",
                description="最小可执行 Skill（inline content）",
            ),
            source="Hello from SkillSpec (inline)!",
            source_type="inline",
        )
    )

    result = await rt.run("skill.hello")
    print(result.status.value)
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())

