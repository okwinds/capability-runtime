from __future__ import annotations

"""
Recipe 示例：01_map_reduce_parallel

演示内容：
- Map-Reduce：spawn_agent 多个子任务 -> wait 汇总 -> report
- 离线 stub collab_manager（可回归）
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
    id: str
    status: str = "running"
    final_output: Optional[str] = None


class StubCollabManager:
    """离线 stub：对齐 spawn/send_input/wait/close/resume 的最小集合。"""

    def __init__(self) -> None:
        self._seq = 1
        self._agents: Dict[str, _Handle] = {}

    def spawn(self, *, message: str, agent_type: str = "default") -> _Handle:
        _ = agent_type
        agent_id = f"stub_{self._seq}"
        self._seq += 1
        h = _Handle(id=agent_id, status="running", final_output=f"map: {message[:60]}")
        self._agents[agent_id] = h
        return h

    def send_input(self, *, agent_id: str, message: str) -> None:
        h = self._agents[agent_id]
        h.final_output = f"input: {message[:60]}"

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


def _build_backend(*, report_md: str) -> FakeChatBackend:
    """离线 Fake backend：spawn 3 个子任务 -> wait -> report。"""

    return FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            LlmToolCall(call_id="s1", name="spawn_agent", args={"message": "summarize part A"}),
                            LlmToolCall(call_id="s2", name="spawn_agent", args={"message": "summarize part B"}),
                            LlmToolCall(call_id="s3", name="spawn_agent", args={"message": "summarize part C"}),
                            LlmToolCall(call_id="w1", name="wait", args={"ids": ["stub_1", "stub_2", "stub_3"], "timeout_ms": 1000}),
                            LlmToolCall(call_id="r1", name="file_write", args={"path": "report.md", "content": report_md}),
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
    parser = argparse.ArgumentParser(description="recipe 01_map_reduce_parallel")
    parser.add_argument("--workspace-root", default=".", help="Workspace root path")
    args = parser.parse_args()

    ws = prepare_example_workspace(
        workspace_root=Path(args.workspace_root).expanduser().resolve(),
        skills={
            "map-reducer": "\n".join(["---", "name: map-reducer", 'description: "map-reduce skill"', "---", "", "# map-reducer", ""]),
        },
        max_steps=60,
        safety_mode="ask",
    )

    report_md = "\n".join(
        [
            "# Map-Reduce Report",
            "",
            "- stub_1: summarize part A",
            "- stub_2: summarize part B",
            "- stub_3: summarize part C",
            "",
        ]
    )

    rt = build_offline_runtime(
        workspace_root=ws.workspace_root,
        overlay_path=ws.overlay_path,
        sdk_backend=_build_backend(report_md=report_md),
        collab_manager=StubCollabManager(),
    )
    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="recipe.map_reduce",
                kind=CapabilityKind.AGENT,
                name="RecipeMapReduce",
                description="离线配方：spawn_agent 并行子任务 -> wait 汇总 -> report.md。",
            ),
            skills=["map-reducer"],
        )
    )
    assert rt.validate() == []

    ctx = ExecutionContext(run_id="recipe_01_map_reduce_parallel", max_depth=5, guards=None, bag={})
    result = asyncio.run(rt.run("recipe.map_reduce", input={}, context=ctx))
    assert result.node_report is not None
    assert (ws.workspace_root / "report.md").exists()
    tools = result.node_report.tool_calls or []
    assert any(t.name == "wait" for t in tools)

    print("EXAMPLE_OK: recipes/01_map_reduce_parallel")
    print(f"wal_locator={result.node_report.events_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

