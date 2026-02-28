"""
01_quickstart：离线 mock 最小闭环。

运行：
  python examples/01_quickstart/run_mock.py
"""

from __future__ import annotations

import asyncio

from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec, Runtime, RuntimeConfig


def handler(spec: AgentSpec, input: dict, context=None):
    """mock_handler：返回一个可回归的确定性输出。"""

    _ = spec
    _ = context
    return {"echo": input}


async def main() -> None:
    """声明 → 注册 → 校验 → 执行。"""

    rt = Runtime(RuntimeConfig(mode="mock", mock_handler=handler))
    rt.register(AgentSpec(base=CapabilitySpec(id="echo", kind=CapabilityKind.AGENT, name="Echo")))
    assert rt.validate() == []

    res = await rt.run("echo", input={"x": 1})
    print("=== 01_quickstart / mock ===")
    print(f"status={res.status.value}")
    print(f"output={res.output}")


if __name__ == "__main__":
    asyncio.run(main())

