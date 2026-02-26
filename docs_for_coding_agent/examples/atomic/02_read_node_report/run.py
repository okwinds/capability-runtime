from __future__ import annotations

"""
Atomic 示例：02_read_node_report

演示内容：
- NodeReport.tool_calls：工具证据（是否成功/错误类型/审批决策）
- NodeReport.activated_skills：skills-first 证据
"""

import argparse
import asyncio
import sys
from pathlib import Path

from skills_runtime.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SRC_ROOT = _REPO_ROOT / "src"
for p in (str(_REPO_ROOT), str(_SRC_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agently_skills_runtime import AgentSpec, CapabilityKind, CapabilitySpec, ExecutionContext  # noqa: E402

from docs_for_coding_agent.examples._shared.example_support import (  # noqa: E402
    build_offline_runtime,
    prepare_example_workspace,
)


def _build_backend() -> FakeChatBackend:
    """离线 Fake backend：一次 shell_exec（返回 0）+ 一次 file_write。"""

    argv = [str(sys.executable), "-c", "print('HELLO');"]
    return FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            LlmToolCall(
                                call_id="t1",
                                name="shell_exec",
                                args={"argv": argv, "timeout_ms": 5000, "sandbox": "none"},
                            ),
                            LlmToolCall(call_id="w1", name="file_write", args={"path": "report.md", "content": "# ok\\n"}),
                        ],
                        finish_reason="tool_calls",
                    ),
                    ChatStreamEvent(type="completed", finish_reason="tool_calls"),
                ]
            ),
            FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="ok"), ChatStreamEvent(type="completed")]),
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="atomic 02_read_node_report")
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
        max_steps=20,
    )
    rt = build_offline_runtime(workspace_root=ws.workspace_root, overlay_path=ws.overlay_path, sdk_backend=_build_backend())
    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="atomic.read_node_report",
                kind=CapabilityKind.AGENT,
                name="AtomicReadNodeReport",
                description="离线示例：调用 shell_exec 与 file_write，然后输出 ok。",
            ),
            skills=["demo-skill"],
        )
    )
    assert rt.validate() == []

    ctx = ExecutionContext(run_id="atomic_02_read_node_report", max_depth=5, guards=None, bag={})
    result = asyncio.run(rt.run("atomic.read_node_report", input={}, context=ctx))
    assert result.node_report is not None

    report = result.node_report
    assert report.events_path is not None and Path(str(report.events_path)).exists()

    assert "demo-skill" in (report.activated_skills or [])

    tools = report.tool_calls or []
    assert any(t.call_id == "t1" and t.name == "shell_exec" for t in tools)
    assert any(t.call_id == "w1" and t.name == "file_write" for t in tools)

    t_shell = next(t for t in tools if t.call_id == "t1")
    assert t_shell.ok is True
    assert t_shell.requires_approval is True
    assert t_shell.approval_decision in {"approved", "approved_for_session"}

    print("EXAMPLE_OK: atomic/02_read_node_report")
    print(f"wal_locator={report.events_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
