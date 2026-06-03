"""
06_responses_bridge：Responses requester opt-in 真实 bridge smoke。

运行：
  1) cp .env.example .env
  2) 编辑 .env 或设置环境变量 OPENAI_API_KEY / OPENAI_BASE_URL / MODEL_NAME
  3) python examples/06_responses_bridge/run.py

缺配置时默认返回非 0，避免把未触达真实 provider 误判为成功；仅当
`CAPRT_EXAMPLE_ALLOW_SKIP=1` 时返回 0。真实运行时通过
RuntimeConfig(requester_strategy="responses") 显式 opt-in，不改变默认 requester。
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

    if not dotenv_path.exists():
        return
    for raw in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def print_env_hint(missing: list[str]) -> None:
    """输出缺配置提示。"""

    print("=== 06_responses_bridge ===")
    print("skip_reason=missing provider configuration")
    print(f"missing={','.join(missing)}")
    print("required=OPENAI_API_KEY,OPENAI_BASE_URL,MODEL_NAME")
    print("responses_is_default=false")


def _skip_exit_code() -> int:
    return 0 if os.getenv("CAPRT_EXAMPLE_ALLOW_SKIP") == "1" else 2


async def main() -> int:
    """运行 Responses bridge 真实 smoke。"""

    load_env(REPO_ROOT / ".env")
    missing = [key for key in REQUIRED if not os.getenv(key)]
    if missing:
        print_env_hint(missing)
        return _skip_exit_code()

    try:
        provider_requester_factory = build_openai_provider_requester_factory(
            base_url=os.environ["OPENAI_BASE_URL"],
            transport_model=os.environ["MODEL_NAME"],
            api_key=os.environ["OPENAI_API_KEY"],
            strategy="responses",
            allow_insecure_transport=os.getenv("CAPRT_REAL_PROVIDER_ALLOW_INSECURE_TRANSPORT") == "1",
        )
    except ModuleNotFoundError:
        print("=== 06_responses_bridge ===")
        print("skip_reason=bridge upstream dependency is not importable")
        print("responses_is_default=false")
        return _skip_exit_code()

    runtime = Runtime(
        RuntimeConfig(
            mode="bridge",
            workspace_root=Path.cwd(),
            preflight_mode="off",
            provider_requester_factory=provider_requester_factory,
            requester_strategy="responses",
        )
    )
    runtime.register(
        AgentSpec(
            base=CapabilitySpec(
                id="agent.responses.smoke",
                kind=CapabilityKind.AGENT,
                name="ResponsesSmoke",
                description="Reply exactly: caprt-runtime-responses-ok",
            ),
            llm_config={"model": os.environ["MODEL_NAME"]},
        )
    )
    assert runtime.validate() == []

    result = await runtime.run("agent.responses.smoke", input={"prompt": "Reply exactly: caprt-runtime-responses-ok"})
    usage = result.node_report.usage if result.node_report is not None else None

    print("=== 06_responses_bridge ===")
    print(f"status={result.status.value}")
    print(f"output_preview={str(result.output)[:220]}")
    print(f"has_node_report={result.node_report is not None}")
    print(f"usage_model={getattr(usage, 'model', None)}")
    print(f"usage_total_tokens={getattr(usage, 'total_tokens', None)}")
    print(f"request_id_present={bool(getattr(usage, 'request_id', None))}")
    print("responses_is_default=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
