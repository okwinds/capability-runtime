"""
01_quickstart：Bridge 接线最小示例（连接真实 LLM）。

运行：
  1) cp examples/01_quickstart/.env.example examples/01_quickstart/.env
  2) 编辑 .env 填入真实配置
  3) python examples/01_quickstart/run_bridge.py

约束：
- 缺少配置时只打印提示并退出（exit code 0），便于离线回归环境跳过。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from agently_skills_runtime import AgentSpec, CapabilityKind, CapabilitySpec, Runtime, RuntimeConfig

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

    print("=== 01_quickstart / bridge ===")
    print("缺少运行所需配置，已退出（exit code 0）。")
    print(f"请准备：{dotenv_path}")
    print("必需变量：OPENAI_API_KEY / OPENAI_BASE_URL / MODEL_NAME")
    if missing:
        print(f"缺失变量：{', '.join(missing)}")


async def main() -> None:
    """执行真实 Bridge 接线（缺依赖时 fail-open 退出）。"""

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
        print("=== 01_quickstart / bridge ===")
        print("环境变量已齐全，但无法导入 agently，已退出（exit code 0）。")
        print("安装：python -m pip install agently")
        return

    Agently.set_settings(
        "OpenAICompatible",
        {
            "base_url": os.environ["OPENAI_BASE_URL"],
            "model": os.environ["MODEL_NAME"],
            "auth": os.environ["OPENAI_API_KEY"],
        },
    )

    rt = Runtime(
        RuntimeConfig(
            mode="bridge",
            workspace_root=Path.cwd(),
            preflight_mode="off",
            agently_agent=Agently.create_agent(),
        )
    )
    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="agent.quickstart.summary",
                kind=CapabilityKind.AGENT,
                name="Quickstart Summary",
                description="用一句中文总结输入主题。",
            )
        )
    )
    assert rt.validate() == []

    result = await rt.run("agent.quickstart.summary", input={"topic": "Capability Runtime 在企业内的落地价值"})
    print("=== 01_quickstart / bridge ===")
    print(f"status={result.status.value}")
    print(f"output_preview={str(result.output)[:220]}")
    print(f"has_node_report={result.node_report is not None}")


if __name__ == "__main__":
    asyncio.run(main())

