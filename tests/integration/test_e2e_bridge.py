from __future__ import annotations

"""
可选集成测试：真实 LLM provider 下的 bridge 端到端冒烟。

注意：
- 默认跳过（避免在离线回归环境中打外网/消耗额度）。
- 启用时需要模型支持 tool calling，否则断言会失败。
- 真实 provider 下，tool calling 往往会产生紧邻的多次 LLM 请求（tool_calls → tool_result → completion）。
  为避免 burst 冲垮 API/触发限流，本文件在 approvals 链路中插入可配置 pause（见 `CAPRT_E2E_LLM_REQUEST_PAUSE_S`）。
"""

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from skills_runtime.safety.approvals import ApprovalDecision, ApprovalProvider, ApprovalRequest
from skills_runtime.tools.protocol import ToolCall, ToolSpec

from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec, Runtime, RuntimeConfig
from capability_runtime.config import CustomTool


pytestmark = pytest.mark.integration

ENABLE = os.getenv("CAPRT_TEST_E2E_BRIDGE") == "1"
if not ENABLE:
    pytest.skip(
        "未启用真实 bridge e2e（默认跳过）。如需运行请设置：CAPRT_TEST_E2E_BRIDGE=1",
        allow_module_level=True,
    )

REQUIRED = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "MODEL_NAME")


def _load_repo_root_dotenv_if_needed() -> None:
    """
    best-effort：当启用真实 e2e 且环境变量缺失时，尝试加载仓库根目录 `.env`（不覆盖已有值）。

    目的：避免“source .env 但未 export”导致本测试被 skip，或 provider 默认回退到非预期模型。
    """

    missing_now = [k for k in REQUIRED if not os.getenv(k)]
    if not missing_now:
        return

    repo_root = Path(__file__).resolve().parents[2]
    dotenv_path = repo_root / ".env"
    if not dotenv_path.exists():
        return

    for raw in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_repo_root_dotenv_if_needed()

missing = [k for k in REQUIRED if not os.getenv(k)]
if missing:
    pytest.skip(
        f"缺少真实 provider 配置：{', '.join(missing)}（请设置 OPENAI_API_KEY/OPENAI_BASE_URL/MODEL_NAME）",
        allow_module_level=True,
    )


def _get_llm_request_pause_s() -> float:
    """读取 E2E real 冒烟的 LLM 请求节流 pause 秒数（float）。

    Env：
    - `CAPRT_E2E_LLM_REQUEST_PAUSE_S`：默认 `1.0`；`0` 表示禁用；负数或不可解析按默认值处理。
    """

    raw = os.getenv("CAPRT_E2E_LLM_REQUEST_PAUSE_S", "1.0")
    try:
        pause_s = float(raw)
    except ValueError:
        return 1.0
    if pause_s < 0:
        return 1.0
    return pause_s


@dataclass
class AutoApproveProvider(ApprovalProvider):
    """集成冒烟用：永远批准（仅用于验证 approvals 事件链路）。

    额外约束：为避免真实 provider 下连续 LLM 请求形成 burst，在 approvals 阶段插入 pause。
    """

    async def request_approval(
        self, *, request: ApprovalRequest, timeout_ms: Optional[int] = None
    ) -> ApprovalDecision:
        _ = request
        _ = timeout_ms
        pause_s = _get_llm_request_pause_s()
        if pause_s > 0:
            await asyncio.sleep(pause_s)
        return ApprovalDecision.APPROVED


def _build_file_write_tool(*, root_dir: Path) -> tuple[ToolSpec, Any]:
    """构造需要审批的 file_write 工具（仅用于集成冒烟）。"""

    artifacts_root = (root_dir / "artifacts").resolve()
    artifacts_root.mkdir(parents=True, exist_ok=True)

    spec = ToolSpec(
        name="file_write",
        description="写入文件（integration smoke）",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        requires_approval=True,
    )

    def handler(call: ToolCall, ctx: Dict[str, Any]) -> Dict[str, Any]:
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


@pytest.mark.asyncio
async def test_e2e_bridge_smoke_tool_call_and_node_report(tmp_path: Path) -> None:
    """验收点：可执行 + tool_call 审批 + NodeReport 证据链存在。"""

    try:
        from agently import Agently  # type: ignore
    except ModuleNotFoundError:
        pytest.skip("未安装 agently（bridge e2e 需要 Agently OpenAICompatible requester）")

    Agently.set_settings(
        "OpenAICompatible",
        {
            "base_url": os.environ["OPENAI_BASE_URL"],
            "model": os.environ["MODEL_NAME"],
            "auth": os.environ["OPENAI_API_KEY"],
        },
    )

    tool_spec, tool_handler = _build_file_write_tool(root_dir=tmp_path)

    rt = Runtime(
        RuntimeConfig(
            mode="bridge",
            workspace_root=tmp_path,
            preflight_mode="off",
            agently_agent=Agently.create_agent(),
            approval_provider=AutoApproveProvider(),
            custom_tools=[CustomTool(spec=tool_spec, handler=tool_handler, override=True)],
        )
    )
    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="agent.e2e",
                kind=CapabilityKind.AGENT,
                name="E2E",
                description=(
                    "你必须调用 tool `file_write` 写入一个 Python 文件。\\n"
                    "要求：写入 artifacts/hello.py，内容是一个可运行的 hello world。\\n"
                    "约束：禁止直接输出代码块；必须通过 tool 写入文件后，再用一句话说明你写了什么。"
                ),
            ),
            llm_config={
                "model": os.environ["MODEL_NAME"],
                "temperature": 0,
                # 更稳：显式要求选择唯一工具，避免 real provider 下 tool_calls 偶发缺失。
                "tool_choice": {"type": "function", "function": {"name": "file_write"}},
            },
        )
    )
    assert rt.validate() == []

    terminal = await rt.run("agent.e2e", input={})
    assert terminal.node_report is not None
    assert terminal.node_report.events_path is not None

    tool_calls = getattr(terminal.node_report, "tool_calls", None) or []
    assert len(tool_calls) >= 1, "模型未触发 tool_call；请确认 provider/模型支持 tools/function calling。"
