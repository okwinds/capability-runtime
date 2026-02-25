from __future__ import annotations

"""
Atomic 示例：08_view_image_offline

演示内容：
- view_image：读取 workspace 内的图片并返回 base64
"""

import argparse
import asyncio
import base64
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


def _write_tiny_png(*, workspace_root: Path) -> None:
    """
    写入一张 1x1 PNG（用于离线 view_image 回归）。

    说明：使用固定 base64，避免依赖 PIL 等外部库。
    """

    b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMA"
        "ASsJTYQAAAAASUVORK5CYII="
    )
    (workspace_root / "tiny.png").write_bytes(base64.b64decode(b64))


def _build_backend() -> FakeChatBackend:
    """离线 Fake backend：调用 view_image。"""

    return FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[LlmToolCall(call_id="img1", name="view_image", args={"path": "tiny.png"})],
                        finish_reason="tool_calls",
                    ),
                    ChatStreamEvent(type="completed", finish_reason="tool_calls"),
                ]
            ),
            FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="ok"), ChatStreamEvent(type="completed")]),
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="atomic 08_view_image_offline")
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
        max_steps=5,
    )
    _write_tiny_png(workspace_root=ws.workspace_root)

    rt = build_offline_runtime(workspace_root=ws.workspace_root, overlay_path=ws.overlay_path, sdk_backend=_build_backend())
    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="atomic.view_image",
                kind=CapabilityKind.AGENT,
                name="AtomicViewImageOffline",
                description="离线示例：调用 view_image，然后输出 ok。",
            ),
            skills=["demo-skill"],
        )
    )
    assert rt.validate() == []

    ctx = ExecutionContext(run_id="atomic_08_view_image_offline", max_depth=5, guards=None, bag={})
    result = asyncio.run(rt.run("atomic.view_image", input={}, context=ctx))
    assert result.node_report is not None

    tools = result.node_report.tool_calls or []
    t = next(x for x in tools if x.call_id == "img1")
    assert t.name == "view_image"
    assert t.ok is True
    assert isinstance((t.data or {}).get("mime"), str)
    b64 = (t.data or {}).get("base64") if isinstance(t.data, dict) else None
    assert isinstance(b64, str) and len(b64) > 10

    print("EXAMPLE_OK: atomic/08_view_image_offline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

