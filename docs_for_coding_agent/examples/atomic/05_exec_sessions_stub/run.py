from __future__ import annotations

"""
Atomic 示例：05_exec_sessions_stub

演示内容：
- exec_command 需要注入 exec_sessions provider
- 离线 stub：不真正启动进程，也能回归 tool_calls 证据结构
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from skills_runtime.core.exec_sessions import ExecSessionWriteResult, ExecSessionsProvider
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


@dataclass
class _StubSession:
    """stub session：只保留 session_id。"""

    session_id: int


class StubExecSessions(ExecSessionsProvider):
    """
    离线 stub ExecSessionsProvider。

    目标：
    - 让 exec_command 工具可以跑通并产出稳定证据；
    - 不依赖真实 PTY/子进程（避免平台差异导致回归不稳定）。
    """

    def __init__(self) -> None:
        self._next_id = 1
        self._alive: set[int] = set()
        self._writes: dict[int, int] = {}

    def spawn(self, *, argv: list[str], cwd: Path, env: Optional[Mapping[str, str]] = None, tty: bool = True) -> Any:
        _ = (argv, cwd, env, tty)
        sid = self._next_id
        self._next_id += 1
        self._alive.add(sid)
        return _StubSession(session_id=sid)

    def write(self, *, session_id: int, chars: str = "", yield_time_ms: int = 50, max_output_bytes: int = 65536) -> ExecSessionWriteResult:
        _ = (chars, yield_time_ms, max_output_bytes)
        if session_id not in self._alive:
            raise KeyError("session not found")
        # 第一次 write：模拟仍在运行（让 exec_command 返回 session_id）
        n = int(self._writes.get(session_id, 0))
        self._writes[session_id] = n + 1
        if n == 0:
            return ExecSessionWriteResult(stdout="STUB_STARTED\n", stderr="", exit_code=None, running=True, truncated=False)
        return ExecSessionWriteResult(stdout="STUB_DONE\n", stderr="", exit_code=0, running=False, truncated=False)

    def has(self, session_id: int) -> bool:
        return session_id in self._alive

    def close(self, session_id: int) -> None:
        self._alive.discard(session_id)

    def close_all(self) -> None:
        self._alive.clear()


def _build_backend() -> FakeChatBackend:
    """离线 Fake backend：exec_command 启动 session，再用 write_stdin 拉取输出并完成。"""

    return FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[LlmToolCall(call_id="e1", name="exec_command", args={"cmd": "echo hi", "yield_time_ms": 1})],
                        finish_reason="tool_calls",
                    ),
                    ChatStreamEvent(type="completed", finish_reason="tool_calls"),
                ]
            ),
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[LlmToolCall(call_id="w2", name="write_stdin", args={"session_id": 1, "chars": "", "yield_time_ms": 1})],
                        finish_reason="tool_calls",
                    ),
                    ChatStreamEvent(type="completed", finish_reason="tool_calls"),
                ]
            ),
            FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="ok"), ChatStreamEvent(type="completed")]),
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="atomic 05_exec_sessions_stub")
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
        max_steps=10,
    )

    rt = build_offline_runtime(
        workspace_root=ws.workspace_root,
        overlay_path=ws.overlay_path,
        sdk_backend=_build_backend(),
        exec_sessions=StubExecSessions(),
    )
    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="atomic.exec_sessions",
                kind=CapabilityKind.AGENT,
                name="AtomicExecSessions",
                description="离线示例：调用 exec_command，然后输出 ok。",
            ),
            skills=["demo-skill"],
        )
    )
    assert rt.validate() == []

    ctx = ExecutionContext(run_id="atomic_05_exec_sessions_stub", max_depth=5, guards=None, bag={})
    result = asyncio.run(rt.run("atomic.exec_sessions", input={}, context=ctx))
    assert result.node_report is not None
    tools = result.node_report.tool_calls or []
    t_exec = next(x for x in tools if x.call_id == "e1")
    assert t_exec.name == "exec_command"
    assert t_exec.ok is True
    assert isinstance(t_exec.data, dict)
    assert isinstance(t_exec.data.get("session_id"), int)
    assert t_exec.data.get("running") is True

    t_wr = next(x for x in tools if x.call_id == "w2")
    assert t_wr.name == "write_stdin"
    assert t_wr.ok is True
    assert isinstance(t_wr.data, dict)
    assert t_wr.data.get("running") is False

    print("EXAMPLE_OK: atomic/05_exec_sessions_stub")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
