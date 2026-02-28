from __future__ import annotations

"""
Atomic 示例：01_sdk_native_minimal

演示内容：
- Runtime.run_stream：先 yield AgentEvent，再 yield CapabilityResult
- NodeReport.engine.module == "skills_runtime"（证据链：执行引擎身份）
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import List

from skills_runtime.core.contracts import AgentEvent
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


def _build_backend() -> FakeChatBackend:
    """离线 Fake backend：写一个文件，然后输出 ok。"""

    return FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[LlmToolCall(call_id="w1", name="file_write", args={"path": "note.txt", "content": "ok\\n"})],
                        finish_reason="tool_calls",
                    ),
                    ChatStreamEvent(type="completed", finish_reason="tool_calls"),
                ]
            ),
            FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="ok"), ChatStreamEvent(type="completed")]),
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="atomic 01_sdk_native_minimal")
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
    rt = build_offline_runtime(workspace_root=ws.workspace_root, overlay_path=ws.overlay_path, sdk_backend=_build_backend())
    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="atomic.sdk_native_stream",
                kind=CapabilityKind.AGENT,
                name="AtomicSdkNativeStream",
                description="离线示例：必须调用 file_write 写 note.txt，然后输出 ok。",
            ),
            skills=["demo-skill"],
        )
    )
    assert rt.validate() == []

    ctx = ExecutionContext(run_id="atomic_01_sdk_native_minimal", max_depth=5, guards=None, bag={})

    events: List[AgentEvent] = []
    terminal = None

    async def _run() -> None:
        nonlocal terminal
        async for item in rt.run_stream("atomic.sdk_native_stream", input={}, context=ctx):
            if isinstance(item, AgentEvent):
                events.append(item)
            else:
                terminal = item

    asyncio.run(_run())
    assert terminal is not None
    assert events, "run_stream should yield AgentEvent before terminal"
    assert terminal.node_report is not None
    assert terminal.node_report.engine and terminal.node_report.engine.get("module") == "skills_runtime"
    assert terminal.node_report.events_path is not None and Path(str(terminal.node_report.events_path)).exists()
    assert (ws.workspace_root / "note.txt").exists()

    print("EXAMPLE_OK: atomic/01_sdk_native_minimal")
    print(f"wal_locator={terminal.node_report.events_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
