"""Agent Domain 脚手架入口：支持 mock / real 双模式。"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

# 允许在未 `pip install -e .` 的情况下直接运行本示例。
REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from capability_runtime import (
    AgentAdapter,
    Runtime,
    RuntimeConfig,
    CapabilityKind,
    CapabilityRuntime,
    RuntimeConfig,
    WorkflowAdapter,
)

from mock_adapter import MockAgentAdapter
from registry import register_all
from storage.file_store import FileStore

REQUIRED_ENV = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "MODEL_NAME")


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="Agent Domain starter")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--mock", action="store_true", help="使用离线 mock adapter 运行")
    mode.add_argument("--real", action="store_true", help="使用真实 Agently bridge 运行")
    return parser.parse_args()


def load_env_file(dotenv_path: Path) -> None:
    """读取 .env 文件并注入环境变量（不覆盖已存在值）。"""
    for raw in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def print_real_mode_hint(dotenv_path: Path, missing: list[str] | None = None) -> None:
    """打印 real 模式缺失条件提示，且约定安全退出。"""
    print("=== 11 agent_domain_starter / real ===")
    print("未满足真实接线条件，已安全退出（exit code 0）。")
    print(f"请准备：{dotenv_path}")
    print("必需变量：OPENAI_API_KEY / OPENAI_BASE_URL / MODEL_NAME")
    if missing:
        print(f"缺失变量：{', '.join(missing)}")


def build_base_runtime() -> CapabilityRuntime:
    """构建基础 runtime，并挂载 workflow adapter。"""
    runtime = CapabilityRuntime(config=RuntimeConfig(max_depth=10))
    runtime.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    return runtime


async def build_mock_runtime() -> CapabilityRuntime:
    """构建 mock 模式 runtime。"""
    runtime = build_base_runtime()
    runtime.set_adapter(CapabilityKind.AGENT, MockAgentAdapter())
    register_all(runtime)
    return runtime


async def build_real_runtime(example_dir: Path) -> CapabilityRuntime | None:
    """构建 real 模式 runtime；条件不满足时返回 None。"""
    dotenv_path = example_dir / ".env"
    if not dotenv_path.exists():
        print_real_mode_hint(dotenv_path)
        return None

    load_env_file(dotenv_path)
    missing = [key for key in REQUIRED_ENV if not os.getenv(key)]
    if missing:
        print_real_mode_hint(dotenv_path, missing)
        return None

    try:
        from agently import Agently
    except ModuleNotFoundError:
        print("=== 11 agent_domain_starter / real ===")
        print("环境变量已齐全，但未安装 agently，已安全退出（exit code 0）。")
        print("安装：pip install agently>=4.0.8")
        return None

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

    runtime = build_base_runtime()
    runtime.set_adapter(CapabilityKind.AGENT, AgentAdapter(runner=bridge.run_async))
    register_all(runtime)
    return runtime


def build_workflow_input() -> dict[str, Any]:
    """构造示例 workflow 输入。"""
    return {
        "raw_idea": "如何在团队中落地 Capability Runtime",
        "audience": "技术团队负责人",
        "target_length": 1500,
    }


async def run(mode: str) -> int:
    """按指定模式执行 workflow，并保存 artifacts。"""
    example_dir = Path(__file__).resolve().parent
    runtime = await (build_real_runtime(example_dir) if mode == "real" else build_mock_runtime())
    if runtime is None:
        return 0

    run_id = f"example11-{mode}-{uuid.uuid4().hex[:8]}"
    result = await runtime.run("workflow.content.creation", input=build_workflow_input(), run_id=run_id)

    store = FileStore(base_dir="artifacts")
    output_payload = result.output if isinstance(result.output, dict) else {"output": result.output}
    output_path = store.save(run_id, "final_output", output_payload)
    _ = store.save(
        run_id,
        "run_meta",
        {
            "mode": mode,
            "status": result.status.value,
            "error": result.error,
            "duration_ms": result.duration_ms,
        },
    )

    print(f"=== 11 agent_domain_starter / {mode} ===")
    print(f"status={result.status.value}")
    print(f"artifact={output_path}")
    print(json.dumps(output_payload, ensure_ascii=False, indent=2)[:600])
    return 0


async def main() -> None:
    """入口函数：默认 mock，可通过参数切换到 real。"""
    args = parse_args()
    mode = "real" if args.real else "mock"
    code = await run(mode)
    if code != 0:
        raise SystemExit(code)


if __name__ == "__main__":
    asyncio.run(main())
