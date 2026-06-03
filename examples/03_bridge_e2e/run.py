"""
03_bridge_e2e：真实 LLM + tool_call + 自动审批 + NodeReport 证据链（示例）。

运行：
  1) cp examples/03_bridge_e2e/.env.example examples/03_bridge_e2e/.env
  2) 编辑 .env 填入真实配置
  3) python examples/03_bridge_e2e/run.py

注意：
- 该示例用于验证“事件流/证据链闭环”，不是生产配置模板。
- 缺少配置时默认返回非 0；仅当设置 `CAPRT_EXAMPLE_ALLOW_SKIP=1` 时返回 0。
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

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
from capability_runtime import CustomTool

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

    print("=== 03_bridge_e2e ===")
    print("缺少运行所需配置，未触达真实 provider。")
    print(f"请准备：{dotenv_path}")
    print("必需变量：OPENAI_API_KEY / OPENAI_BASE_URL / MODEL_NAME")
    if missing:
        print(f"缺失变量：{', '.join(missing)}")


def _skip_exit_code() -> int:
    return 0 if os.getenv("CAPRT_EXAMPLE_ALLOW_SKIP") == "1" else 2


@dataclass
class AutoApproveProvider:
    """
    示例用审批器：永远批准。

    说明：
    - 该实现用于端到端演示 tool_calls + approvals 的证据链；
    - 生产环境应使用“规则审批 + fail-closed”策略（参考输入文档 SDK-02）。
    """

    async def request_approval(
        self,
        *,
        request: Any,
        timeout_ms: Optional[int] = None,
    ) -> Any:
        from skills_runtime.safety.approvals import ApprovalDecision

        _ = timeout_ms
        approval_key = str(getattr(request, "approval_key", "") or "")
        print(
            "[auto_approve] "
            f"tool={request.tool} "
            f"key={approval_key[:10]} "
            f"summary={request.summary}"
        )
        return ApprovalDecision.APPROVED_FOR_SESSION


def build_file_write_tool(*, root_dir: Path) -> tuple[Any, Any]:
    """
    构造一个需要审批的 file_write 工具（示例）。

    参数：
    - root_dir：允许写入的根目录（只允许写入该目录之下）
    """

    artifacts_root = (root_dir / "artifacts").resolve()
    artifacts_root.mkdir(parents=True, exist_ok=True)

    from skills_runtime.tools.protocol import ToolSpec

    spec = ToolSpec(
        name="file_write",
        description="写入文件（examples/03_bridge_e2e：用于演示 tool_calls/approvals 证据链）",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对 artifacts/ 的路径"},
                "content": {"type": "string", "description": "文件内容"},
            },
            "required": ["path", "content"],
        },
        requires_approval=True,
    )

    def handler(call: Any, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """写入文件并返回写入位置（最小实现）。"""

        _ = ctx
        rel = str(call.args.get("path") or "")
        content = str(call.args.get("content") or "")

        target = (artifacts_root / rel).resolve()
        if not str(target).startswith(str(artifacts_root)):
            raise ValueError("path must be under artifacts/")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(target)}

    return spec, handler


async def main() -> int:
    """跑通一次真实 bridge 执行，并打印证据链摘要。"""

    dotenv_path = Path(__file__).resolve().parent / ".env"
    if not dotenv_path.exists():
        print_env_hint(dotenv_path)
        return _skip_exit_code()

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
        print("=== 03_bridge_e2e ===")
        print("环境变量已齐全，但无法导入 bridge 上游依赖。")
        print("安装项目依赖后重试。")
        return _skip_exit_code()

    workspace_root = Path(__file__).resolve().parent
    tool_spec, tool_handler = build_file_write_tool(root_dir=workspace_root)

    rt = Runtime(
        RuntimeConfig(
            mode="bridge",
            workspace_root=workspace_root,
            preflight_mode="off",
            provider_requester_factory=provider_requester_factory,
            approval_provider=AutoApproveProvider(),
            custom_tools=[CustomTool(spec=tool_spec, handler=tool_handler, override=True)],
        )
    )
    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="agent.bridge.e2e",
                kind=CapabilityKind.AGENT,
                name="BridgeE2E",
                description=(
                    "请调用 tool `file_write` 写入一个 Python 文件，然后用一句话说明你写了什么。\n"
                    "要求：写入 hello.py（相对 artifacts/），内容是一个可运行的 hello world。"
                ),
            ),
            llm_config={"model": os.environ["MODEL_NAME"]},
        )
    )
    assert rt.validate() == []

    got_events = 0
    terminal = None
    async for item in rt.run_stream("agent.bridge.e2e", input={}):
        if hasattr(item, "type"):
            got_events += 1
        else:
            terminal = item

    print("=== 03_bridge_e2e ===")
    print(f"events_forwarded={got_events}")
    if terminal is None:
        print("no terminal CapabilityResult (unexpected)")
        return 1

    print(f"status={terminal.status.value}")
    print(f"output_preview={str(terminal.output)[:220]}")
    print(f"has_node_report={terminal.node_report is not None}")
    if terminal.node_report is not None:
        print(f"events_path={terminal.node_report.events_path!r}")
        print(f"tool_calls={len(getattr(terminal.node_report, 'tool_calls', []) or [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
