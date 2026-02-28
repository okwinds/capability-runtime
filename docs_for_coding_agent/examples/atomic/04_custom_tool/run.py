from __future__ import annotations

"""
Atomic 示例：04_custom_tool

演示内容：
- 自定义工具注入（CustomTool + ToolSpec + handler）
- NodeReport.tool_calls 中出现自定义工具调用证据
"""

import argparse
import asyncio
import sys
from pathlib import Path

from skills_runtime.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall
from skills_runtime.tools.protocol import ToolCall, ToolResult, ToolSpec
from skills_runtime.tools.registry import ToolExecutionContext

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SRC_ROOT = _REPO_ROOT / "src"
for p in (str(_REPO_ROOT), str(_SRC_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec, ExecutionContext  # noqa: E402
from capability_runtime import CustomTool  # noqa: E402

from docs_for_coding_agent.examples._shared.example_support import (  # noqa: E402
    build_offline_runtime,
    prepare_example_workspace,
)


def _host_ping(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
    """
    自定义工具 handler：返回一个固定 payload。

    参数：
    - call：工具调用（args 可为空）
    - ctx：工具执行上下文（本例不使用）
    """

    _ = (call, ctx)
    return ToolResult.ok_payload(stdout="pong", data={"pong": True})


def _build_backend() -> FakeChatBackend:
    """离线 Fake backend：调用 host_ping。"""

    return FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[LlmToolCall(call_id="p1", name="host_ping", args={})],
                        finish_reason="tool_calls",
                    ),
                    ChatStreamEvent(type="completed", finish_reason="tool_calls"),
                ]
            ),
            FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="ok"), ChatStreamEvent(type="completed")]),
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="atomic 04_custom_tool")
    parser.add_argument("--workspace-root", default=".", help="Workspace root path")
    args = parser.parse_args()

    ws = prepare_example_workspace(
        workspace_root=Path(args.workspace_root).expanduser().resolve(),
        skills={
            "demo-skill": "\n".join(
                [
                    "---",
                    "name: demo-skill",
                    'description: "demo skill for atomic examples"',
                    "---",
                    "",
                    "# Demo Skill",
                    "",
                ]
            )
        },
    )

    spec = ToolSpec(
        name="host_ping",
        description="宿主自定义工具：返回 pong。",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        requires_approval=False,
        idempotency="safe",
    )
    custom = CustomTool(spec=spec, handler=_host_ping, override=False)

    rt = build_offline_runtime(
        workspace_root=ws.workspace_root,
        overlay_path=ws.overlay_path,
        sdk_backend=_build_backend(),
        custom_tools=[custom],
    )
    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="atomic.custom_tool",
                kind=CapabilityKind.AGENT,
                name="AtomicCustomTool",
                description="离线示例：调用 host_ping，然后输出 ok。",
            ),
            skills=["demo-skill"],
        )
    )
    assert rt.validate() == []

    ctx = ExecutionContext(run_id="atomic_04_custom_tool", max_depth=5, guards=None, bag={})
    result = asyncio.run(rt.run("atomic.custom_tool", input={}, context=ctx))
    assert result.node_report is not None
    tools = result.node_report.tool_calls or []
    assert any(t.name == "host_ping" and t.call_id == "p1" and t.ok is True for t in tools)

    print("EXAMPLE_OK: atomic/04_custom_tool")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
