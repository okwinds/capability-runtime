from __future__ import annotations

"""
Recipe 示例：04_invoke_capability_child_agent

演示内容：
- skills 驱动的 Agent（outer）触发 invoke_capability
- invoke_capability 在宿主侧委托执行子 Agent（child.echo）
- 证据链闭环：NodeReport.tool_calls + WAL approvals/tool evidence

离线运行：
  python docs_for_coding_agent/examples/recipes/04_invoke_capability_child_agent/run.py --workspace-root /tmp/caprt-recipe-04
"""

import argparse
import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List

from skills_runtime.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SRC_ROOT = _REPO_ROOT / "src"
for p in (str(_REPO_ROOT), str(_SRC_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec, ExecutionContext  # noqa: E402
from capability_runtime import InvokeCapabilityAllowlist, make_invoke_capability_tool  # noqa: E402

from docs_for_coding_agent.examples._shared.example_support import (  # noqa: E402
    build_offline_runtime,
    prepare_example_workspace,
)


def _build_outer_backend() -> FakeChatBackend:
    """离线 Fake backend：invoke_capability(child.echo) → 输出 ok。"""

    return FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            LlmToolCall(
                                call_id="ic1",
                                name="invoke_capability",
                                args={"capability_id": "child.echo", "input": {"x": 1}},
                            )
                        ],
                        finish_reason="tool_calls",
                    ),
                    ChatStreamEvent(type="completed", finish_reason="tool_calls"),
                ]
            ),
            FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="ok"), ChatStreamEvent(type="completed")]),
        ]
    )


def _build_child_backend() -> FakeChatBackend:
    """离线 Fake backend：child.echo 直接输出 child。"""

    return FakeChatBackend(
        calls=[FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="child"), ChatStreamEvent(type="completed")])]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="recipe 04_invoke_capability_child_agent")
    parser.add_argument("--workspace-root", default=".", help="Workspace root path")
    args = parser.parse_args()

    ws = prepare_example_workspace(
        workspace_root=Path(args.workspace_root).expanduser().resolve(),
        skills={
            "delegator": "\n".join(
                [
                    "---",
                    "name: delegator",
                    'description: "demo skill for invoke_capability recipe"',
                    "---",
                    "",
                    "# Delegator",
                    "",
                ]
            )
        },
        safety_mode="ask",
        max_steps=30,
    )

    outer_cfg = replace(
        build_offline_runtime(
            workspace_root=ws.workspace_root,
            overlay_path=ws.overlay_path,
            sdk_backend=_build_outer_backend(),
            preflight_mode="off",
        ).config,
        sdk_backend=_build_outer_backend(),
    )

    child_cfg = replace(outer_cfg, sdk_backend=_build_child_backend(), custom_tools=[])

    invoke_tool = make_invoke_capability_tool(
        child_runtime_config=child_cfg,
        child_specs=[
            AgentSpec(
                base=CapabilitySpec(
                    id="child.echo",
                    kind=CapabilityKind.AGENT,
                    name="ChildEcho",
                    description="子 Agent：用于演示 invoke_capability。",
                )
            )
        ],
        allowlist=InvokeCapabilityAllowlist(allowed_ids=["child.echo"]),
        requires_approval=True,
    )

    rt = build_offline_runtime(
        workspace_root=ws.workspace_root,
        overlay_path=ws.overlay_path,
        sdk_backend=_build_outer_backend(),
        preflight_mode="off",
        custom_tools=[invoke_tool],
    )
    rt.register_many(
        [
            AgentSpec(
                base=CapabilitySpec(
                    id="recipe.invoke_capability.child_agent",
                    kind=CapabilityKind.AGENT,
                    name="RecipeInvokeCapabilityChildAgent",
                    description="必须调用 invoke_capability 执行 child.echo，然后输出 ok。",
                ),
                skills=["delegator"],
            ),
        ]
    )
    assert rt.validate() == []

    ctx = ExecutionContext(run_id="recipe_04_invoke_capability_child_agent", max_depth=5, guards=None, bag={})
    result = asyncio.run(rt.run("recipe.invoke_capability.child_agent", input={}, context=ctx))
    assert result.node_report is not None
    assert result.node_report.events_path is not None
    wal = Path(str(result.node_report.events_path))
    assert wal.exists()

    # evidence：NodeReport.tool_calls 必须包含 invoke_capability（tool evidence）
    tools = result.node_report.tool_calls or []
    inv = next((t for t in tools if t.name == "invoke_capability"), None)
    assert inv is not None
    assert inv.ok is True
    assert isinstance(inv.data, dict)
    artifact_path = Path(str(inv.data.get("artifact_path") or ""))
    assert artifact_path.exists()
    obj = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert obj.get("schema") == "capability-runtime.invoke_capability.v1"

    print("EXAMPLE_OK: recipes/04_invoke_capability_child_agent")
    print(f"wal_locator={result.node_report.events_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
