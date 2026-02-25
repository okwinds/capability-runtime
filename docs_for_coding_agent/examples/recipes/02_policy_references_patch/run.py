from __future__ import annotations

"""
Recipe 示例：02_policy_references_patch

演示内容：
- skill_ref_read 读取受限 references（可审计、可控泄露面）
- policy 驱动 apply_patch 的最小闭环
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


def _build_backend(*, policy_skill_mention: str) -> FakeChatBackend:
    """离线 Fake backend：skill_ref_read -> apply_patch -> report。"""

    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: app.py",
            "@@",
            "-def greet(name: str) -> str:",
            "-    return f\"hi, {name}\"",
            "+def greet(name: str) -> str:",
            "+    # policy: use a clearer greeting",
            "+    return f\"hello, {name}\"",
            "*** End Patch",
            "",
        ]
    )

    report_md = "\n".join(
        [
            "# Policy/References Patch Report",
            "",
            f"- policy: {policy_skill_mention} / references/policy.md",
            "- patch: app.py greet() greeting text",
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
                            LlmToolCall(
                                call_id="ref1",
                                name="skill_ref_read",
                                args={"skill_mention": policy_skill_mention, "ref_path": "references/policy.md"},
                            ),
                            LlmToolCall(call_id="patch1", name="apply_patch", args={"input": patch}),
                            LlmToolCall(call_id="w1", name="file_write", args={"path": "report.md", "content": report_md}),
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
    parser = argparse.ArgumentParser(description="recipe 02_policy_references_patch")
    parser.add_argument("--workspace-root", default=".", help="Workspace root path")
    args = parser.parse_args()

    ws = prepare_example_workspace(
        workspace_root=Path(args.workspace_root).expanduser().resolve(),
        skills={
            "policy-guides": "\n".join(
                [
                    "---",
                    "name: policy-guides",
                    'description: "policy skill with references/"',
                    "---",
                    "",
                    "# policy-guides",
                    "",
                ]
            ),
        },
        max_steps=30,
        safety_mode="ask",
        enable_references=True,
    )

    # 写入 references/policy.md（受限引用目录）
    policy_dir = ws.skills_root / "policy-guides" / "references"
    policy_dir.mkdir(parents=True, exist_ok=True)
    (policy_dir / "policy.md").write_text(
        "\n".join(
            [
                "# Policy",
                "",
                "- greet() 必须使用 'hello' 作为开头",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # 目标代码（待补丁）
    (ws.workspace_root / "app.py").write_text(
        "\n".join(["def greet(name: str) -> str:", "    return f\"hi, {name}\"", ""]) + "\n",
        encoding="utf-8",
    )

    mention = "$[examples:agent].policy-guides"
    rt = build_offline_runtime(
        workspace_root=ws.workspace_root,
        overlay_path=ws.overlay_path,
        sdk_backend=_build_backend(policy_skill_mention=mention),
    )
    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="recipe.policy_references_patch",
                kind=CapabilityKind.AGENT,
                name="RecipePolicyReferencesPatch",
                description="离线配方：skill_ref_read(policy) -> apply_patch -> report。",
            ),
            skills=["policy-guides"],
        )
    )
    assert rt.validate() == []

    ctx = ExecutionContext(run_id="recipe_02_policy_references_patch", max_depth=5, guards=None, bag={})
    result = asyncio.run(rt.run("recipe.policy_references_patch", input={}, context=ctx))
    assert result.node_report is not None
    assert (ws.workspace_root / "report.md").exists()

    tools = result.node_report.tool_calls or []
    assert any(t.name == "skill_ref_read" and t.ok is True for t in tools)
    assert any(t.name == "apply_patch" and t.ok is True for t in tools)

    # 补丁生效（确定性）
    assert "hello," in (ws.workspace_root / "app.py").read_text(encoding="utf-8")

    print("EXAMPLE_OK: recipes/02_policy_references_patch")
    print(f"wal_locator={result.node_report.events_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

