from __future__ import annotations

"""
Recipe 示例：00_review_fix_qa_report

演示内容：
- Review→Fix→QA→Report 的最小交付闭环
- 证据链：tool_calls（pytest + apply_patch）与 WAL locator
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


def _build_backend(*, calc_py: str, test_py: str, report_md: str) -> FakeChatBackend:
    """离线 Fake backend：pytest fail -> apply_patch -> pytest ok -> report。"""

    pytest_argv = [str(sys.executable), "-m", "pytest", "-q", "test_calc.py"]
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: calc.py",
            "@@",
            "-def add(a: int, b: int) -> int:",
            "-    return a - b",
            "+def add(a: int, b: int) -> int:",
            "+    return a + b",
            "*** End Patch",
            "",
        ]
    )

    plan_1 = {
        "explanation": "Review→Fix→QA→Report",
        "plan": [
            {"step": "写入最小项目", "status": "in_progress"},
            {"step": "复现失败", "status": "pending"},
            {"step": "最小修复", "status": "pending"},
            {"step": "回归验证", "status": "pending"},
            {"step": "输出报告", "status": "pending"},
        ],
    }
    plan_2 = {
        "explanation": "完成",
        "plan": [
            {"step": "写入最小项目", "status": "completed"},
            {"step": "复现失败", "status": "completed"},
            {"step": "最小修复", "status": "completed"},
            {"step": "回归验证", "status": "completed"},
            {"step": "输出报告", "status": "completed"},
        ],
    }

    return FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            LlmToolCall(call_id="p1", name="update_plan", args=plan_1),
                            LlmToolCall(call_id="w_calc", name="file_write", args={"path": "calc.py", "content": calc_py}),
                            LlmToolCall(call_id="w_test", name="file_write", args={"path": "test_calc.py", "content": test_py}),
                            LlmToolCall(call_id="t_fail", name="shell_exec", args={"argv": pytest_argv, "timeout_ms": 15000, "sandbox": "none"}),
                            LlmToolCall(call_id="patch", name="apply_patch", args={"input": patch}),
                            LlmToolCall(call_id="t_ok", name="shell_exec", args={"argv": pytest_argv, "timeout_ms": 15000, "sandbox": "none"}),
                            LlmToolCall(call_id="p2", name="update_plan", args=plan_2),
                            LlmToolCall(call_id="w_report", name="file_write", args={"path": "report.md", "content": report_md}),
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
    parser = argparse.ArgumentParser(description="recipe 00_review_fix_qa_report")
    parser.add_argument("--workspace-root", default=".", help="Workspace root path")
    args = parser.parse_args()

    ws = prepare_example_workspace(
        workspace_root=Path(args.workspace_root).expanduser().resolve(),
        skills={
            "recipe-reviewer": "\n".join(["---", "name: recipe-reviewer", 'description: "review skill"', "---", "", "# recipe-reviewer", ""]),
            "recipe-patcher": "\n".join(["---", "name: recipe-patcher", 'description: "patch skill"', "---", "", "# recipe-patcher", ""]),
            "recipe-qa-reporter": "\n".join(["---", "name: recipe-qa-reporter", 'description: "qa+report skill"', "---", "", "# recipe-qa-reporter", ""]),
        },
        max_steps=80,
        safety_mode="ask",
    )

    calc_py = "def add(a: int, b: int) -> int:\\n    return a - b\\n"
    test_py = "from calc import add\\n\\n\\ndef test_add():\\n    assert add(1, 2) == 3\\n"
    report_md = "\n".join(
        [
            "# Review Fix QA Report",
            "",
            "- issue: `add` implementation bug (subtraction vs addition)",
            "- verification: `python -m pytest -q test_calc.py`",
            "- outputs: calc.py, test_calc.py, report.md",
            "",
        ]
    )

    rt = build_offline_runtime(
        workspace_root=ws.workspace_root,
        overlay_path=ws.overlay_path,
        sdk_backend=_build_backend(calc_py=calc_py, test_py=test_py, report_md=report_md),
    )
    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="recipe.review_fix_qa_report",
                kind=CapabilityKind.AGENT,
                name="RecipeReviewFixQaReport",
                description="离线配方：pytest fail -> apply_patch -> pytest ok -> report。",
            ),
            skills=["recipe-reviewer", "recipe-patcher", "recipe-qa-reporter"],
        )
    )
    assert rt.validate() == []

    ctx = ExecutionContext(run_id="recipe_00_review_fix_qa_report", max_depth=5, guards=None, bag={})
    result = asyncio.run(rt.run("recipe.review_fix_qa_report", input={}, context=ctx))
    assert result.node_report is not None
    assert (ws.workspace_root / "report.md").exists()

    tools = result.node_report.tool_calls or []
    assert any(t.name == "apply_patch" for t in tools)
    assert any(t.name == "shell_exec" for t in tools)

    print("EXAMPLE_OK: recipes/00_review_fix_qa_report")
    print(f"wal_locator={result.node_report.events_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

