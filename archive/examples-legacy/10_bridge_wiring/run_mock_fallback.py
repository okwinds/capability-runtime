"""Bridge 接线降级示例：当 agently 不可用时使用离线 runner 保持同一声明模式。"""
from __future__ import annotations

import asyncio

from capability_runtime import (
    AgentIOSchema,
    AgentAdapter,
    AgentSpec,
    CapabilityKind,
    CapabilityRuntime,
    CapabilitySpec,
    CapabilityStatus,
    RuntimeConfig,
)


async def offline_runner(task: str, *, initial_history: list | None = None) -> str:
    """离线 runner：返回 task 摘要，模拟真实桥接的文本输出。"""
    _ = initial_history
    compact = " ".join(task.split())
    return f"[mock-bridge-summary] {compact[:180]}"


async def main() -> None:
    """运行离线降级版 bridge 示例。"""
    runtime = CapabilityRuntime(config=RuntimeConfig())
    runtime.set_adapter(CapabilityKind.AGENT, AgentAdapter(runner=offline_runner))

    runtime.register(
        AgentSpec(
            base=CapabilitySpec(
                id="agent.bridge.summary",
                kind=CapabilityKind.AGENT,
                name="Bridge Summary Agent (Mock)",
                description="Offline fallback for bridge wiring demo.",
            ),
            prompt_template="请用一句中文总结主题：{topic}",
            system_prompt="你是一个简洁、准确的技术写作助手。",
            output_schema=AgentIOSchema(fields={"summary": "str"}, required=["summary"]),
        )
    )

    result = await runtime.run(
        "agent.bridge.summary",
        input={"topic": "Capability Runtime 在企业内的落地价值"},
    )
    if result.status != CapabilityStatus.SUCCESS:
        raise RuntimeError(f"Fallback run failed: {result.error}")

    print("=== 10 bridge_wiring / mock_fallback ===")
    print(f"status={result.status.value}")
    print(f"output_preview={str(result.output)[:220]}")


if __name__ == "__main__":
    asyncio.run(main())
