from __future__ import annotations

"""
Recipe 示例：03_skill_exec_actions

演示内容：
- skills.actions.enabled=true
- skill bundle 的 SKILL.md frontmatter.actions 声明一个 build action（shell）
- LLM tool_call：skill_exec(skill_mention, action_id)
- approvals：skill_exec requires_approval=true（WAL/NodeReport 可审计）
"""

import argparse
import asyncio
import json
import sys
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

from docs_for_coding_agent.examples._shared.example_support import (  # noqa: E402
    build_offline_runtime,
    write_filesystem_skills_bundle,
    write_sdk_overlay_for_examples,
)


def _load_wal_events(*, wal_locator: str) -> List[Dict[str, Any]]:
    """读取 WAL（events.jsonl）并返回 JSON object 列表。"""

    p = Path(wal_locator)
    if not p.exists():
        raise AssertionError(f"wal_locator does not exist: {wal_locator}")
    events: List[Dict[str, Any]] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        events.append(json.loads(line))
    return events


def _write_action_script(*, skill_dir: Path) -> None:
    """
    在 skill bundle 内写入 actions/build.py（被 skill_exec 受控执行）。

    约束：
    - 脚本必须位于 `<bundle_root>/actions/` 下
    - action.argv 需以 `actions/` 相对路径引用脚本（由上游校验）
    """

    actions_dir = skill_dir / "actions"
    actions_dir.mkdir(parents=True, exist_ok=True)
    (actions_dir / "build.py").write_text(
        "\n".join(
            [
                "import json",
                "import os",
                "from pathlib import Path",
                "",
                "def main() -> int:",
                "    ws = os.environ.get('SKILLS_RUNTIME_SDK_WORKSPACE_ROOT', '').strip()",
                "    mention = os.environ.get('SKILLS_RUNTIME_SDK_SKILL_MENTION', '').strip()",
                "    action_id = os.environ.get('SKILLS_RUNTIME_SDK_SKILL_ACTION_ID', '').strip()",
                "    if not ws:",
                "        raise SystemExit('missing env: SKILLS_RUNTIME_SDK_WORKSPACE_ROOT')",
                "    out = {",
                "        'ok': True,",
                "        'action': action_id,",
                "        'skill_mention': mention,",
                "        'artifact': 'action_artifact.json',",
                "    }",
                "    p = Path(ws) / 'action_artifact.json'",
                "    p.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\\n', encoding='utf-8')",
                "    print('ACTION_OK')",
                "    return 0",
                "",
                "if __name__ == '__main__':",
                "    raise SystemExit(main())",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _build_backend(*, skill_mention: str) -> FakeChatBackend:
    """离线 Fake backend：skill_exec(build) → 输出 ok。"""

    return FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            LlmToolCall(
                                call_id="tc_skill_exec",
                                name="skill_exec",
                                args={"skill_mention": skill_mention, "action_id": "build"},
                            ),
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
    parser = argparse.ArgumentParser(description="recipe 03_skill_exec_actions")
    parser.add_argument("--workspace-root", default=".", help="Workspace root path")
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root).expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)

    namespace = "acme:platform:runtime"
    skill_name = "artifact_builder"
    skill_mention = f"$[{namespace}].{skill_name}"

    # 1) skills bundle：SKILL.md frontmatter.actions + actions/ 脚本
    skills_root = write_filesystem_skills_bundle(
        workspace_root=workspace_root,
        skills={
            skill_name: "\n".join(
                [
                    "---",
                    f"name: {skill_name}",
                    'description: "demo skill for skill_exec actions example"',
                    "actions:",
                    "  build:",
                    "    argv:",
                    "      - python",
                    "      - actions/build.py",
                    "    timeout_ms: 8000",
                    "---",
                    "",
                    "# Artifact Builder",
                    "",
                ]
            )
        },
    )
    _write_action_script(skill_dir=(skills_root / skill_name).resolve())

    # 2) overlay：actions.enabled=true + namespace space
    overlay_path = write_sdk_overlay_for_examples(
        workspace_root=workspace_root,
        skills_root=skills_root,
        max_steps=15,
        safety_mode="ask",
        namespace=namespace,
        enable_references=False,
        enable_actions=True,
    )

    rt = build_offline_runtime(
        workspace_root=workspace_root,
        overlay_path=overlay_path,
        sdk_backend=_build_backend(skill_mention=skill_mention),
    )
    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="recipe.skill_exec_actions",
                kind=CapabilityKind.AGENT,
                name="RecipeSkillExecActions",
                description="离线示例：必须调用 skill_exec 执行 build action，然后输出 ok。",
            ),
            skills=[skill_name],
        )
    )
    assert rt.validate() == []

    ctx = ExecutionContext(run_id="recipe_03_skill_exec_actions", max_depth=5, guards=None, bag={})
    result = asyncio.run(rt.run("recipe.skill_exec_actions", input={}, context=ctx))

    assert result.node_report is not None
    assert result.node_report.events_path is not None
    assert Path(str(result.node_report.events_path)).exists()

    artifact_path = workspace_root / "action_artifact.json"
    assert artifact_path.exists()
    assert "\"ok\": true" in artifact_path.read_text(encoding="utf-8")

    # evidence：NodeReport.tool_calls 必须包含 skill_exec（tool evidence）
    tool_names = [t.name for t in (result.node_report.tool_calls or [])]
    assert "skill_exec" in tool_names, tool_names

    # evidence：WAL 中必须包含 approvals + tool_call_finished(skill_exec)
    wal_events = _load_wal_events(wal_locator=str(result.node_report.events_path))
    assert any(ev.get("type") == "approval_requested" for ev in wal_events)
    assert any(ev.get("type") == "approval_decided" for ev in wal_events)

    skill_exec_finished_ok = False
    for ev in wal_events:
        if ev.get("type") != "tool_call_finished":
            continue
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("tool") != "skill_exec":
            continue
        result_obj = payload.get("result") or {}
        if isinstance(result_obj, dict) and result_obj.get("ok") is True:
            skill_exec_finished_ok = True
            break
    assert skill_exec_finished_ok

    print("EXAMPLE_OK: recipes/03_skill_exec_actions")
    print(f"namespace={namespace}")
    print(f"skill_mention={skill_mention}")
    print(f"wal_locator={result.node_report.events_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

