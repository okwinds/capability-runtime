from __future__ import annotations

"""
Atomic 示例：03_preflight_gate

演示内容：
- preflight_mode=error：遇到 overlay 问题 fail-closed（events_path=None）
- preflight_mode=warn：继续执行，并将 preflight_issues 写入 NodeReport.meta
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
    """离线 Fake backend：写一个文件，然后输出 ok。"""

    return FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[LlmToolCall(call_id="w1", name="file_write", args={"path": "ok.txt", "content": "ok\\n"})],
                        finish_reason="tool_calls",
                    ),
                    ChatStreamEvent(type="completed", finish_reason="tool_calls"),
                ]
            ),
            FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="ok"), ChatStreamEvent(type="completed")]),
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="atomic 03_preflight_gate")
    parser.add_argument("--workspace-root", default=".", help="Workspace root path")
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root).expanduser().resolve()
    ws = prepare_example_workspace(
        workspace_root=workspace_root,
        skills={
            "demo-skill": "\n".join(
                [
                    "---",
                    "name: demo-skill",
                    'description: "demo skill for preflight examples"',
                    "---",
                    "",
                    "# Demo Skill",
                    "",
                ]
            )
        },
        max_steps=10,
        safety_mode="ask",
    )

    # 构造一份“合法但会产生 preflight issues”的 skills_config：
    # - versioning 是占位配置：启用后会产生 warning issue（用于演示 gate）
    skills_config = {
        "versioning": {"enabled": True, "strategy": "TODO"},
        "strictness": {
            "unknown_mention": "error",
            "duplicate_name": "error",
            "mention_format": "strict",
        },
        "references": {"enabled": False},
        "actions": {"enabled": False},
        "spaces": [
            {
                "id": "example-space",
                "namespace": "examples:agent",
                "sources": ["example-fs"],
                "enabled": True,
            }
        ],
        "sources": [
            {
                "id": "example-fs",
                "type": "filesystem",
                "options": {"root": str(ws.skills_root.resolve())},
            }
        ],
    }

    def _register(rt) -> None:
        rt.register(
            AgentSpec(
                base=CapabilitySpec(
                    id="atomic.preflight_gate",
                    kind=CapabilityKind.AGENT,
                    name="AtomicPreflightGate",
                    description="离线示例：调用 file_write 写 ok.txt，然后输出 ok。",
                ),
                skills=["demo-skill"],
            )
        )

    # --- error：fail-closed（不产生 WAL；events_path=None）---
    rt_error = build_offline_runtime(
        workspace_root=ws.workspace_root,
        overlay_path=ws.overlay_path,
        sdk_backend=_build_backend(),
        preflight_mode="error",
        skills_config=skills_config,
    )
    _register(rt_error)
    ctx_err = ExecutionContext(run_id="atomic_03_preflight_error", max_depth=5, guards=None, bag={})
    res_err = asyncio.run(rt_error.run("atomic.preflight_gate", input={}, context=ctx_err))
    assert res_err.status.value == "failed"
    assert res_err.node_report is not None
    assert res_err.node_report.events_path is None
    assert res_err.node_report.meta.get("preflight_mode") == "error"

    # --- warn：继续执行（产生 WAL；meta 包含 issues）---
    rt_warn = build_offline_runtime(
        workspace_root=ws.workspace_root,
        overlay_path=ws.overlay_path,
        sdk_backend=_build_backend(),
        preflight_mode="warn",
        skills_config=skills_config,
    )
    _register(rt_warn)
    ctx_warn = ExecutionContext(run_id="atomic_03_preflight_warn", max_depth=5, guards=None, bag={})
    res_warn = asyncio.run(rt_warn.run("atomic.preflight_gate", input={}, context=ctx_warn))
    assert res_warn.node_report is not None
    assert res_warn.node_report.events_path is not None and Path(str(res_warn.node_report.events_path)).exists()
    assert res_warn.node_report.meta.get("preflight_mode") == "warn"
    assert isinstance(res_warn.node_report.meta.get("preflight_issues"), list)

    print("EXAMPLE_OK: atomic/03_preflight_gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
