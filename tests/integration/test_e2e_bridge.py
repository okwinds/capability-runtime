from __future__ import annotations

"""
可选集成测试：真实 LLM provider 下的 bridge 端到端冒烟。

注意：
- 默认跳过（避免在离线回归环境中打外网/消耗额度）。
- 启用时需要模型支持 tool calling，否则断言会失败。
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from skills_runtime.safety.approvals import ApprovalDecision, ApprovalProvider, ApprovalRequest
from skills_runtime.tools.protocol import ToolCall, ToolSpec

from agently_skills_runtime import AgentSpec, CapabilityKind, CapabilitySpec, Runtime, RuntimeConfig
from agently_skills_runtime.config import CustomTool


pytestmark = pytest.mark.integration

ENABLE = os.getenv("AGENTLY_SKILLS_RUNTIME_TEST_E2E_BRIDGE") == "1"
if not ENABLE:
    pytest.skip(
        "未启用真实 bridge e2e（默认跳过）。如需运行请设置：AGENTLY_SKILLS_RUNTIME_TEST_E2E_BRIDGE=1",
        allow_module_level=True,
    )

REQUIRED = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "MODEL_NAME")
missing = [k for k in REQUIRED if not os.getenv(k)]
if missing:
    pytest.skip(
        f"缺少真实 provider 配置：{', '.join(missing)}（请设置 OPENAI_API_KEY/OPENAI_BASE_URL/MODEL_NAME）",
        allow_module_level=True,
    )


@dataclass
class AutoApproveProvider(ApprovalProvider):
    """集成冒烟用：永远批准（仅用于验证 approvals 事件链路）。"""

    async def request_approval(
        self, *, request: ApprovalRequest, timeout_ms: Optional[int] = None
    ) -> ApprovalDecision:
        _ = request
        _ = timeout_ms
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
                    "请调用 tool `file_write` 写入一个 Python 文件，然后用一句话说明你写了什么。\\n"
                    "要求：写入 artifacts/hello.py，内容是一个可运行的 hello world。"
                ),
            )
        )
    )
    assert rt.validate() == []

    terminal = await rt.run("agent.e2e", input={})
    assert terminal.node_report is not None
    assert terminal.node_report.events_path is not None

    tool_calls = getattr(terminal.node_report, "tool_calls", None) or []
    assert len(tool_calls) >= 1, "模型未触发 tool_call；请确认 provider/模型支持 tools/function calling。"
