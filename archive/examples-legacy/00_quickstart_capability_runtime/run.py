"""快速体验 CapabilityRuntime + AgentAdapter 的离线示例（方案2）。"""

from __future__ import annotations

import asyncio

from capability_runtime import (
    AgentAdapter,
    AgentSpec,
    CapabilityKind,
    CapabilityRuntime,
    CapabilitySpec,
    RuntimeConfig,
)


async def _offline_runner(task: str, *, initial_history=None) -> str:
    """
    离线 runner：把 task 回显为 output（便于本地验证）。

    参数：
    - task: AgentAdapter 组织后的任务文本
    - initial_history: 兼容签名保留（本示例不使用）
    """

    _ = initial_history
    return f"[offline-output] {task}"


async def main() -> None:
    """
    30 秒体验：
    - 声明一个 AgentSpec（prompt_template + system_prompt）
    - 注册到 CapabilityRuntime
    - 用离线 runner 执行并打印结果
    """

    rt = CapabilityRuntime(config=RuntimeConfig())
    rt.set_adapter(CapabilityKind.AGENT, AgentAdapter(runner=_offline_runner))

    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="agent.hello",
                kind=CapabilityKind.AGENT,
                name="Hello Agent",
                description="最小可执行 Agent（离线 runner）",
            ),
            system_prompt="你是一个简洁、准确的中文助手。",
            prompt_template="请用一句话总结主题：{topic}",
        )
    )

    result = await rt.run("agent.hello", input={"topic": "capability-runtime 的定位"})
    print(result.status.value)
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())

