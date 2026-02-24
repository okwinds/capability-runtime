"""
04_triggerflow_orchestration：TriggerFlow 顶层编排多个 Runtime.run()（示例）。

运行：
  1) cp examples/04_triggerflow_orchestration/.env.example examples/04_triggerflow_orchestration/.env
  2) 编辑 .env 填入真实配置
  3) python examples/04_triggerflow_orchestration/run.py

注意：
- 该示例展示“顶层编排”，不通过 SDK Agent tool 触发 TriggerFlow（按输入文档 2.5 决策）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

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


def print_env_hint(dotenv_path: Path, missing: Optional[list[str]] = None) -> None:
    """输出环境缺失提示并说明退出行为。"""

    print("=== 04_triggerflow_orchestration ===")
    print("缺少运行所需配置，已退出（exit code 0）。")
    print(f"请准备：{dotenv_path}")
    print("必需变量：OPENAI_API_KEY / OPENAI_BASE_URL / MODEL_NAME")
    if missing:
        print(f"缺失变量：{', '.join(missing)}")


def main() -> None:
    """构造 TriggerFlow 并启动一次执行。"""

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
        from agently import Agently, TriggerFlow  # type: ignore
    except ModuleNotFoundError:
        print("=== 04_triggerflow_orchestration ===")
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

    runtime = Runtime(
        RuntimeConfig(
            mode="bridge",
            workspace_root=Path(__file__).resolve().parent,
            preflight_mode="off",
            agently_agent=Agently.create_agent(),
        )
    )
    runtime.register_many(
        [
            AgentSpec(
                base=CapabilitySpec(
                    id="agent.analyze",
                    kind=CapabilityKind.AGENT,
                    name="Analyze",
                    description="分析主题并给出三条要点（中文）。",
                )
            ),
            AgentSpec(
                base=CapabilitySpec(
                    id="agent.write",
                    kind=CapabilityKind.AGENT,
                    name="Write",
                    description="根据分析结果写一段简短说明（中文，<= 120 字）。",
                )
            ),
        ]
    )
    assert runtime.validate() == []

    flow = TriggerFlow(name="runtime-orchestration-demo")

    @flow.chunk
    async def analyze(data: Any):
        topic = getattr(data, "value", data)
        r = await runtime.run("agent.analyze", input={"topic": topic})
        return {"topic": topic, "analysis": r.output, "report": r.node_report}

    @flow.chunk
    async def write(data: Any):
        payload = getattr(data, "value", data) or {}
        r = await runtime.run(
            "agent.write",
            input={"topic": payload.get("topic"), "analysis": payload.get("analysis")},
        )
        return {"final": r.output, "report": r.node_report}

    flow.to(analyze).to(write)
    out = flow.start("为什么系统级证据链对 LLM 编排很重要？", wait_for_result=True, timeout=60)

    print("=== 04_triggerflow_orchestration ===")
    print(out)


if __name__ == "__main__":
    main()

