"""
Bridge 接线示例：通过 capability-runtime 调用真实 LLM。

前置条件：
  1. pip install -e ".[dev]"
  2. pip install agently>=4.0.8
  3. cp examples/10_bridge_wiring/.env.example examples/10_bridge_wiring/.env
  4. 编辑 .env 填入真实的 API key 和 endpoint

运行方法：
  python examples/10_bridge_wiring/run.py
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from capability_runtime import (
    AgentIOSchema,
    AgentAdapter,
    AgentSpec,
    Runtime,
    RuntimeConfig,
    CapabilityKind,
    CapabilityRuntime,
    CapabilitySpec,
    RuntimeConfig,
)

REQUIRED = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "MODEL_NAME")


def load_env(dotenv_path: Path) -> None:
    """读取 `.env` 并写入进程环境（不覆盖已有值）。"""
    for raw in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def print_env_hint(dotenv_path: Path, missing: list[str] | None = None) -> None:
    """输出环境缺失提示并说明退出行为。"""
    print("=== 10 bridge_wiring ===")
    print("缺少运行所需配置，已退出（exit code 0）。")
    print(f"请准备：{dotenv_path}")
    print("必需变量：OPENAI_API_KEY / OPENAI_BASE_URL / MODEL_NAME")
    if missing:
        print(f"缺失变量：{', '.join(missing)}")


async def main() -> None:
    """执行真实 Bridge 接线，缺依赖时只提示不抛异常。"""
    dotenv_path = Path(__file__).resolve().parent / ".env"
    if not dotenv_path.exists():
        print_env_hint(dotenv_path)
        return

    load_env(dotenv_path)
    missing = [key for key in REQUIRED if not os.getenv(key)]
    if missing:
        print_env_hint(dotenv_path, missing)
        return

    try:
        from agently import Agently  # type: ignore
    except ModuleNotFoundError:
        print("=== 10 bridge_wiring ===")
        print("环境变量已齐全，但无法导入 agently，已退出（exit code 0）。")
        print("安装：pip install agently>=4.0.8")
        print("降级：python examples/10_bridge_wiring/run_mock_fallback.py")
        return

    Agently.set_settings(
        "OpenAICompatible",
        {
            "base_url": os.environ["OPENAI_BASE_URL"],
            "model": os.environ["MODEL_NAME"],
            "auth": os.environ["OPENAI_API_KEY"],
        },
    )
    bridge = Runtime(
        agently_agent=Agently.create_agent(),
        config=RuntimeConfig(
            workspace_root=Path.cwd(),
            config_paths=[],
            preflight_mode="off",
            upstream_verification_mode="off",
        ),
    )

    runtime = CapabilityRuntime(config=RuntimeConfig())
    runtime.set_adapter(CapabilityKind.AGENT, AgentAdapter(runner=bridge.run_async))
    runtime.register(
        AgentSpec(
            base=CapabilitySpec(id="agent.bridge.summary", kind=CapabilityKind.AGENT, name="Bridge Summary Agent"),
            prompt_template="请用一句中文总结主题：{topic}",
            system_prompt="你是一个简洁、准确的技术写作助手。",
            output_schema=AgentIOSchema(fields={"summary": "str"}, required=["summary"]),
        )
    )

    result = await runtime.run("agent.bridge.summary", input={"topic": "Capability Runtime 在企业内的落地价值"})
    print("=== 10 bridge_wiring ===")
    print(f"status={result.status.value}")
    print(f"output_preview={str(result.output)[:220]}")


if __name__ == "__main__":
    asyncio.run(main())
