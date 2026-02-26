from __future__ import annotations

"""
Atomic 示例：00_runtime_minimal

演示内容：
- Runtime.register / validate / run
- 离线注入 FakeChatBackend（走真实 skills_runtime.core.agent.Agent loop）
- 产出可审计证据链：WAL locator（NodeReportV2.events_path）
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
    """
    构造离线 Fake backend：调用 apply_patch 写入 hello.txt。

    说明：
    - apply_patch 需要审批；可在 NodeReport.tool_calls 中看到 approval decision。
    """

    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Add File: hello.txt",
            "+hello",
            "*** End Patch",
            "",
        ]
    )
    return FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            LlmToolCall(call_id="c1", name="apply_patch", args={"input": patch}),
                        ],
                        finish_reason="tool_calls",
                    ),
                    ChatStreamEvent(type="completed", finish_reason="tool_calls"),
                ]
            ),
            FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="done"), ChatStreamEvent(type="completed")]),
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="atomic 00_runtime_minimal")
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
                id="atomic.runtime_minimal",
                kind=CapabilityKind.AGENT,
                name="AtomicRuntimeMinimal",
                description="离线示例：必须调用 apply_patch 添加 hello.txt，然后输出 done。",
            ),
            skills=["demo-skill"],
        )
    )
    assert rt.validate() == []

    ctx = ExecutionContext(run_id="atomic_00_runtime_minimal", max_depth=5, guards=None, bag={})
    result = asyncio.run(rt.run("atomic.runtime_minimal", input={}, context=ctx))

    assert result.node_report is not None
    assert result.node_report.events_path is not None
    assert Path(str(result.node_report.events_path)).exists()
    assert (ws.workspace_root / "hello.txt").exists()

    print("EXAMPLE_OK: atomic/00_runtime_minimal")
    print(f"wal_locator={result.node_report.events_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
