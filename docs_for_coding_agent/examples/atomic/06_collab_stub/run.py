from __future__ import annotations

"""
Atomic 示例：06_collab_stub

演示内容：
- collab tools 需要注入 collab_manager
- 离线 stub：回归 tool_calls 结构（spawn_agent/wait/close_agent）
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from skills_runtime.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SRC_ROOT = _REPO_ROOT / "src"
for p in (str(_REPO_ROOT), str(_SRC_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec, ExecutionContext  # noqa: E402

from docs_for_coding_agent.examples._shared.example_support import (  # noqa: E402
    build_offline_runtime,
    prepare_example_workspace,
)


@dataclass
class _Handle:
    """child agent handle（最小字段集合）。"""

    id: str
    status: str = "running"
    final_output: Optional[str] = None


class StubCollabManager:
    """
    离线 stub collab manager。

    约定（对齐上游 tools）：
    - spawn(message, agent_type) -> handle(id,status,...)
    - send_input(agent_id,message)
    - wait(ids, timeout_ms) -> handles[]
    - close(agent_id)
    - resume(agent_id) -> handle
    """

    def __init__(self) -> None:
        self._seq = 1
        self._agents: Dict[str, _Handle] = {}

    def spawn(self, *, message: str, agent_type: str = "default") -> _Handle:
        _ = agent_type
        agent_id = f"stub_{self._seq}"
        self._seq += 1
        h = _Handle(id=agent_id, status="running", final_output=f"started: {message[:40]}")
        self._agents[agent_id] = h
        return h

    def send_input(self, *, agent_id: str, message: str) -> None:
        h = self._agents[agent_id]
        h.final_output = f"got_input: {message[:40]}"

    def wait(self, *, ids: List[str], timeout_ms: Optional[int] = None) -> List[_Handle]:
        _ = timeout_ms
        out: List[_Handle] = []
        for i in ids:
            h = self._agents[i]
            h.status = "completed"
            if h.final_output is None:
                h.final_output = "completed"
            out.append(h)
        return out

    def close(self, *, agent_id: str) -> None:
        _ = self._agents.pop(agent_id)

    def resume(self, *, agent_id: str) -> _Handle:
        return self._agents[agent_id]

    def get(self, *, agent_id: str) -> _Handle:
        return self._agents[agent_id]


def _build_backend() -> FakeChatBackend:
    """离线 Fake backend：spawn_agent -> send_input -> wait -> close_agent。"""

    return FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            LlmToolCall(call_id="s1", name="spawn_agent", args={"message": "do sub task", "agent_type": "default"}),
                            LlmToolCall(call_id="i1", name="send_input", args={"id": "stub_1", "message": "ping"}),
                            LlmToolCall(call_id="w1", name="wait", args={"ids": ["stub_1"], "timeout_ms": 1000}),
                            LlmToolCall(call_id="c1", name="close_agent", args={"id": "stub_1"}),
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
    parser = argparse.ArgumentParser(description="atomic 06_collab_stub")
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

    rt = build_offline_runtime(
        workspace_root=ws.workspace_root,
        overlay_path=ws.overlay_path,
        sdk_backend=_build_backend(),
        collab_manager=StubCollabManager(),
    )
    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="atomic.collab",
                kind=CapabilityKind.AGENT,
                name="AtomicCollab",
                description="离线示例：调用 spawn_agent/wait/close_agent，然后输出 ok。",
            ),
            skills=["demo-skill"],
        )
    )
    assert rt.validate() == []

    ctx = ExecutionContext(run_id="atomic_06_collab_stub", max_depth=5, guards=None, bag={})
    result = asyncio.run(rt.run("atomic.collab", input={}, context=ctx))
    assert result.node_report is not None

    tools = result.node_report.tool_calls or []
    assert any(t.name == "spawn_agent" and t.call_id == "s1" and t.ok is True for t in tools)
    t_wait = next(t for t in tools if t.call_id == "w1")
    results = (t_wait.data or {}).get("results") if isinstance(t_wait.data, dict) else None
    assert isinstance(results, list) and results
    assert results[0].get("status") == "completed"

    print("EXAMPLE_OK: atomic/06_collab_stub")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

