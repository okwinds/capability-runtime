from __future__ import annotations

"""
Atomic 示例：09_multiseg_namespace_mention

演示内容：
- skills-runtime-sdk==0.1.5.post1：skills.spaces schema 使用 namespace（可多段）
- strict mention：$[namespace].skill_name（namespace ≥ 3 segments）
- 可观察证据：
  - stdout 打印 namespace + expected mention
  - WAL 中存在 skill_injected(mention_text=expected)
  - NodeReport.activated_skills 记录被注入的 skill_name
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

from agently_skills_runtime import AgentSpec, CapabilityKind, CapabilitySpec, ExecutionContext  # noqa: E402

from docs_for_coding_agent.examples._shared.example_support import (  # noqa: E402
    build_offline_runtime,
    write_filesystem_skills_bundle,
    write_sdk_overlay_for_examples,
)


def _build_backend() -> FakeChatBackend:
    """离线 Fake backend：写一个文件，然后输出 ok。"""

    return FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            LlmToolCall(
                                call_id="w1",
                                name="file_write",
                                args={"path": "ok.txt", "content": "ok\n"},
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


def main() -> int:
    parser = argparse.ArgumentParser(description="atomic 09_multiseg_namespace_mention")
    parser.add_argument("--workspace-root", default=".", help="Workspace root path")
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root).expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)

    skills_root = write_filesystem_skills_bundle(
        workspace_root=workspace_root,
        skills={
            "demo-skill": "\n".join(
                [
                    "---",
                    "name: demo-skill",
                    'description: "demo skill for multi-segment namespace example"',
                    "---",
                    "",
                    "# Demo Skill",
                    "",
                ]
            )
        },
    )

    namespace = "acme:platform:runtime"
    expected_mention = f"$[{namespace}].demo-skill"
    overlay_path = write_sdk_overlay_for_examples(
        workspace_root=workspace_root,
        skills_root=skills_root,
        max_steps=10,
        safety_mode="ask",
        namespace=namespace,
        enable_references=False,
        enable_actions=False,
    )

    rt = build_offline_runtime(workspace_root=workspace_root, overlay_path=overlay_path, sdk_backend=_build_backend())
    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="atomic.multiseg_namespace_mention",
                kind=CapabilityKind.AGENT,
                name="AtomicMultiSegNamespaceMention",
                description="离线示例：必须调用 file_write 写 ok.txt，然后输出 ok。",
            ),
            skills=["demo-skill"],
        )
    )
    assert rt.validate() == []

    ctx = ExecutionContext(run_id="atomic_09_multiseg_namespace_mention", max_depth=5, guards=None, bag={})
    result = asyncio.run(rt.run("atomic.multiseg_namespace_mention", input={}, context=ctx))

    assert result.node_report is not None
    assert result.node_report.events_path is not None
    assert Path(str(result.node_report.events_path)).exists()
    assert (workspace_root / "ok.txt").exists()

    # evidence：WAL 中应出现 skill_injected(mention_text=expected_mention)
    events = _load_wal_events(wal_locator=str(result.node_report.events_path))
    injected_mentions = []
    for ev in events:
        if ev.get("type") != "skill_injected":
            continue
        payload = ev.get("payload") or {}
        if isinstance(payload, dict) and payload.get("mention_text"):
            injected_mentions.append(str(payload.get("mention_text")))
    assert expected_mention in injected_mentions, injected_mentions

    assert "demo-skill" in (result.node_report.activated_skills or [])

    print("EXAMPLE_OK: atomic/09_multiseg_namespace_mention")
    print(f"namespace={namespace}")
    print(f"expected_mention={expected_mention}")
    print(f"wal_locator={result.node_report.events_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

