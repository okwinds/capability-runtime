"""示例 01：声明两个 Agent，并通过 mock 适配器执行。"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from agently_skills_runtime import (
    AgentSpec,
    CapabilityKind,
    CapabilityResult,
    CapabilityRuntime,
    CapabilitySpec,
    CapabilityStatus,
    ExecutionContext,
    RuntimeConfig,
)


class MockAgentAdapter:
    """为演示 Agent 返回可预测输出。"""

    async def execute(
        self,
        *,
        spec: AgentSpec,
        input: dict[str, Any],
        context: ExecutionContext,
        runtime: CapabilityRuntime,
    ) -> CapabilityResult:
        """按 capability id 执行 Agent 并返回 mock 输出。"""
        _ = context
        _ = runtime
        agent_id = spec.base.id

        if agent_id == "agent.greeter":
            name = str(input.get("name", "world"))
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={
                    "message": f"Hello, {name}!",
                    "agent_id": agent_id,
                },
            )

        if agent_id == "agent.calculator":
            a = int(input.get("a", 0))
            b = int(input.get("b", 0))
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={
                    "sum": a + b,
                    "product": a * b,
                    "agent_id": agent_id,
                },
            )

        return CapabilityResult(
            status=CapabilityStatus.FAILED,
            error=f"Unsupported agent id: {agent_id}",
        )


def pretty(data: Any) -> str:
    """将 JSON 输出格式化为便于终端阅读的文本。"""
    return json.dumps(data, ensure_ascii=False, indent=2)


async def main() -> None:
    """构建 runtime，注册规格，完成校验、执行并打印输出。"""
    runtime = CapabilityRuntime(config=RuntimeConfig())
    runtime.set_adapter(CapabilityKind.AGENT, MockAgentAdapter())

    greeter = AgentSpec(
        base=CapabilitySpec(
            id="agent.greeter",
            kind=CapabilityKind.AGENT,
            name="Greeter Agent",
            description="Return a greeting message.",
        )
    )
    calculator = AgentSpec(
        base=CapabilitySpec(
            id="agent.calculator",
            kind=CapabilityKind.AGENT,
            name="Calculator Agent",
            description="Return arithmetic results.",
        )
    )

    runtime.register_many([greeter, calculator])
    missing = runtime.validate()
    if missing:
        raise RuntimeError(f"Missing capabilities: {missing}")

    greeter_result = await runtime.run("agent.greeter", input={"name": "Alice"})
    calculator_result = await runtime.run("agent.calculator", input={"a": 7, "b": 3})

    print("=== 01 declare_and_run ===")
    print(f"greeter.status={greeter_result.status.value}")
    print(pretty(greeter_result.output))
    print(f"calculator.status={calculator_result.status.value}")
    print(pretty(calculator_result.output))


if __name__ == "__main__":
    asyncio.run(main())
