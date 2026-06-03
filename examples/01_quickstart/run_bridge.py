"""
01_quickstart：Bridge 接线最小示例（连接真实 LLM）。

运行：
  1) cp examples/01_quickstart/.env.example examples/01_quickstart/.env
  2) 编辑 .env 填入真实配置
  3) python examples/01_quickstart/run_bridge.py

约束：
- 缺少配置时默认返回非 0，避免把未触达真实 provider 误判为成功。
- 仅当设置 `CAPRT_EXAMPLE_ALLOW_SKIP=1` 时返回 0，供离线回归显式跳过。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
for path in (REPO_ROOT, SRC_ROOT):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from capability_runtime import (
    AgentSpec,
    CapabilityKind,
    CapabilitySpec,
    Runtime,
    RuntimeConfig,
    build_openai_provider_requester_factory,
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

    print("=== 01_quickstart / bridge ===")
    print("缺少运行所需配置，未触达真实 provider。")
    print(f"请准备：{dotenv_path}")
    print("必需变量：OPENAI_API_KEY / OPENAI_BASE_URL / MODEL_NAME")
    if missing:
        print(f"缺失变量：{', '.join(missing)}")


def _skip_exit_code() -> int:
    return 0 if os.getenv("CAPRT_EXAMPLE_ALLOW_SKIP") == "1" else 2


async def main() -> int:
    """执行真实 Bridge 接线（缺依赖/缺配置时默认 fail-closed）。

    说明：当前 legacy bridge 仍需要宿主注入运行期上游 agent。该接线被
    隔离在示例 bootstrap 内；应用侧稳定依赖面仍是 Runtime / RuntimeConfig。
    """

    dotenv_path = Path(__file__).resolve().parent / ".env"
    if dotenv_path.exists():
        load_env(dotenv_path)
    missing = [key for key in REQUIRED if not os.getenv(key)]
    if missing:
        print_env_hint(dotenv_path, missing)
        return _skip_exit_code()

    try:
        provider_requester_factory = build_openai_provider_requester_factory(
            base_url=os.environ["OPENAI_BASE_URL"],
            transport_model=os.environ["MODEL_NAME"],
            api_key=os.environ["OPENAI_API_KEY"],
            strategy="chat_completions",
            allow_insecure_transport=os.getenv("CAPRT_REAL_PROVIDER_ALLOW_INSECURE_TRANSPORT") == "1",
        )
    except ModuleNotFoundError:
        print("=== 01_quickstart / bridge ===")
        print("环境变量已齐全，但无法导入 bridge 上游依赖。")
        print("安装项目依赖后重试。")
        return _skip_exit_code()

    rt = Runtime(
        RuntimeConfig(
            mode="bridge",
            workspace_root=Path.cwd(),
            preflight_mode="off",
            provider_requester_factory=provider_requester_factory,
        )
    )
    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="agent.quickstart.summary",
                kind=CapabilityKind.AGENT,
                name="Quickstart Summary",
                description="用一句中文总结输入主题。",
            ),
            # Runtime bridge 的实际请求模型以 SDK ChatRequest.model 为准；
            # AgentSpec.llm_config.model 是业务侧稳定入口，不要只依赖 transport settings。
            llm_config={"model": os.environ["MODEL_NAME"]},
        )
    )
    assert rt.validate() == []

    result = await rt.run("agent.quickstart.summary", input={"topic": "Capability Runtime 在企业内的落地价值"})
    print("=== 01_quickstart / bridge ===")
    print(f"status={result.status.value}")
    print(f"output_preview={str(result.output)[:220]}")
    print(f"has_node_report={result.node_report is not None}")
    usage = result.node_report.usage if result.node_report is not None else None
    print(f"usage_model={getattr(usage, 'model', None)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
