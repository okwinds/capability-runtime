from __future__ import annotations

"""
ci_failure_triage_and_fix：面向人类的小 app/MVP（skills-first）。

双模式：
- offline：FakeChatBackend 驱动真实 skills_runtime.Agent loop（可回归）
- real：真模型（OpenAI-compatible，经 Agently requester 作为传输层）
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional

from skills_runtime.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall
from skills_runtime.safety.approvals import ApprovalDecision

from agently_skills_runtime import AgentSpec, CapabilityKind, CapabilitySpec, Runtime

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from examples.apps._shared.app_support import (  # noqa: E402
    AutoApprovalProvider,
    build_evidence_strict_output_validator,
    ScriptedApprovalProvider,
    TerminalApprovalProvider,
    TerminalHumanIO,
    build_bridge_runtime_from_env,
    env_or_default,
    load_env_file,
    missing_artifacts,
    write_overlay_for_app,
)


def _build_offline_backend(*, app_py: str, test_py: str, report_md: str) -> FakeChatBackend:
    """离线 Fake backend：写项目 → pytest fail → apply_patch → pytest ok → report。"""

    pytest_argv = [str(sys.executable), "-m", "pytest", "-q", "test_app.py"]
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: app.py",
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
        "explanation": "CI triage：复现失败",
        "plan": [
            {"step": "写入最小项目", "status": "in_progress"},
            {"step": "复现失败", "status": "pending"},
            {"step": "最小修复", "status": "pending"},
            {"step": "回归验证", "status": "pending"},
            {"step": "输出报告", "status": "pending"},
        ],
    }
    plan_2 = {
        "explanation": "CI triage：修复并验证通过",
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
                            LlmToolCall(call_id="w_app", name="file_write", args={"path": "app.py", "content": app_py}),
                            LlmToolCall(call_id="w_test", name="file_write", args={"path": "test_app.py", "content": test_py}),
                            LlmToolCall(
                                call_id="t_fail",
                                name="shell_exec",
                                args={"argv": pytest_argv, "timeout_ms": 15000, "sandbox": "none"},
                            ),
                            LlmToolCall(call_id="patch", name="apply_patch", args={"input": patch}),
                            LlmToolCall(
                                call_id="t_ok",
                                name="shell_exec",
                                args={"argv": pytest_argv, "timeout_ms": 15000, "sandbox": "none"},
                            ),
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


def _register_capability(runtime: Runtime) -> None:
    """注册本 app 的 Agent 能力（skills-first）。"""

    runtime.register(
        AgentSpec(
            base=CapabilitySpec(
                id="app.ci_failure_triage_and_fix",
                kind=CapabilityKind.AGENT,
                name="CiFailureTriageAndFix",
                description="\n".join(
                    [
                        "你正在运行一个 CI 失败排障与修复闭环示例。",
                        "必须使用工具完成：",
                        "- 读取/确认 workspace 下的 app.py/test_app.py（不要重写基线文件）",
                        "- shell_exec(pytest) 复现失败",
                        "- apply_patch 最小修复",
                        "- shell_exec(pytest) 验证通过",
                        "- file_write(report.md)",
                        "注意：输出报告中要包含修复点与验证命令。",
                    ]
                ),
            ),
            skills=["ci-log-analyzer", "ci-patcher", "ci-qa-reporter"],
            system_prompt="\n".join(
                [
                    "执行协议（必须严格遵守；示例目的：先失败再修复）：",
                    "A) 只允许 **一轮** tool_calls，且必须按顺序包含以下 4 个调用：",
                    "   1) shell_exec：args 必须是 {argv:[\"python\",\"-m\",\"pytest\",\"-q\",\"test_app.py\"], timeout_ms:15000, sandbox:\"none\"}（预期失败；ok=false 正常；不要设置 cwd）",
                    "   2) apply_patch：args 必须是 {input: host_patch}（只修 add 逻辑；禁止用 file_write 重写 app.py/test_app.py）",
                    "   3) shell_exec：args 同第 1 步（必须通过；stdout 应包含 1 passed；不要设置 cwd）",
                    "   4) file_write(report.md)：args 必须是 {path:\"report.md\", content: host_report_md_template}",
                    "B) 上述 4 个 tool_calls 执行完成后：下一条消息 **只能输出纯文本 `ok`**，不得再调用任何工具（否则视为失败）。",
                ]
            ),
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="ci_failure_triage_and_fix (offline/real)")
    parser.add_argument("--workspace-root", default=".", help="Workspace root path")
    parser.add_argument("--mode", choices=["offline", "real"], default="offline", help="Run mode")
    parser.add_argument(
        "--non-interactive",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Non-interactive mode (auto approvals).",
    )
    parser.add_argument(
        "--strict",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Fail-closed if required artifacts are missing.",
    )
    parser.add_argument(
        "--evidence-strict",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Fail-closed if required tool evidence is missing; disable host fallback.",
    )
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root).expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)

    app_dir = Path(__file__).resolve().parent
    skills_root = (app_dir / "skills").resolve()
    overlay = write_overlay_for_app(
        workspace_root=workspace_root,
        skills_root=skills_root,
        max_steps=120,
        safety_mode="ask",
        planner_model=env_or_default("MODEL_NAME", "gpt-4o-mini") if args.mode == "real" else None,
        executor_model=env_or_default("MODEL_NAME", "gpt-4o-mini") if args.mode == "real" else None,
    )

    if args.mode == "offline":
        app_py = "def add(a: int, b: int) -> int:\n    return a - b\n"
        test_py = "from app import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
        report_md = "\n".join(
            [
                "# CI Triage Report",
                "",
                "- issue: pytest failed (add function bug)",
                "- fix: change `add(a,b)` from subtraction to addition",
                "- verification: `python -m pytest -q test_app.py` passed",
                "",
            ]
        )
        runtime = build_bridge_runtime_from_env(
            workspace_root=workspace_root,
            overlay=overlay,
            sdk_backend=_build_offline_backend(app_py=app_py, test_py=test_py, report_md=report_md),
            approval_provider=ScriptedApprovalProvider(
                decisions=[
                    ApprovalDecision.APPROVED_FOR_SESSION,  # file_write app.py
                    ApprovalDecision.APPROVED_FOR_SESSION,  # file_write test_app.py
                    ApprovalDecision.APPROVED_FOR_SESSION,  # shell_exec fail
                    ApprovalDecision.APPROVED_FOR_SESSION,  # apply_patch
                    ApprovalDecision.APPROVED_FOR_SESSION,  # shell_exec ok
                    ApprovalDecision.APPROVED_FOR_SESSION,  # file_write report.md
                ]
            ),
            human_io=None,
        )
        _register_capability(runtime)
        assert runtime.validate() == []
        result = asyncio.run(runtime.run("app.ci_failure_triage_and_fix", input={"evidence_strict": False}))
        print("EXAMPLE_OK: ci_failure_triage_and_fix")
        if result.node_report and result.node_report.events_path:
            print(f"wal_locator={result.node_report.events_path}")
        return 0

    dotenv_path = app_dir / ".env"
    if dotenv_path.exists():
        load_env_file(dotenv_path)

    # real demo：为模型提供一套“可复现的失败基线”，避免直接从零写出一个全通过项目而失去教学意义。
    # 约束：
    # - 若用户已在 workspace 放置了自己的 app/test，则不覆盖（尊重用户输入）。
    app_py_path = workspace_root / "app.py"
    test_py_path = workspace_root / "test_app.py"
    if not app_py_path.exists():
        app_py_path.write_text("def add(a: int, b: int) -> int:\n    return a - b\n", encoding="utf-8")
    if not test_py_path.exists():
        test_py_path.write_text(
            "from app import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
            encoding="utf-8",
        )

    try:
        output_validator = None
        output_validation_mode = "off"
        if args.evidence_strict:
            output_validation_mode = "error"
            output_validator = build_evidence_strict_output_validator(
                schema_id="examples.ci_failure_triage_and_fix.evidence_strict.v1",
                require_file_writes=["report.md"],
                require_tools_ok=["apply_patch", "shell_exec"],
                forbid_file_writes=["app.py", "test_app.py"],
            )

        runtime = build_bridge_runtime_from_env(
            workspace_root=workspace_root,
            overlay=overlay,
            sdk_backend=None,
            approval_provider=AutoApprovalProvider() if args.non_interactive else TerminalApprovalProvider(),
            human_io=TerminalHumanIO(),
            output_validation_mode=output_validation_mode,
            output_validator=output_validator,
        )
    except Exception as exc:
        print("=== ci_failure_triage_and_fix ===")
        print("缺少真实模型配置，已退出（exit code 0）。")
        print("请准备：examples/apps/ci_failure_triage_and_fix/.env")
        print("必需变量：OPENAI_API_KEY / OPENAI_BASE_URL / MODEL_NAME")
        print(f"error={type(exc).__name__}: {exc}")
        return 0

    _register_capability(runtime)
    assert runtime.validate() == []
    pytest_argv = [str(sys.executable), "-m", "pytest", "-q", "test_app.py"]
    host_patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: app.py",
            "@@",
            "-def add(a: int, b: int) -> int:",
            "-    return a - b",
            "+def add(a: int, b: int) -> int:",
            "+    return a + b",
            "*** End Patch",
            "",
        ]
    )
    host_report_md_template = "\n".join(
        [
            "# CI Triage Report",
            "",
            "## 结论",
            "- issue: `add(a,b)` 使用了减法导致测试失败",
            "- fix: 使用 apply_patch 将减法改为加法",
            "",
            "## 验证命令",
            "- `python -m pytest -q test_app.py`",
            "",
            "## 证据链指针",
            "- wal_locator/events_path: <see terminal output>",
            "",
        ]
    )
    result = asyncio.run(
        runtime.run(
            "app.ci_failure_triage_and_fix",
            input={
                "evidence_strict": bool(args.evidence_strict),
                "pytest_argv": pytest_argv,
                "host_patch": host_patch,
                "host_report_md_template": host_report_md_template,
            },
        )
    )
    print("\n[final_output]\n")
    print(result.output)
    if result.node_report and result.node_report.events_path:
        print(f"\nwal_locator={result.node_report.events_path}")

    if result.node_report is not None:
        ov = (result.node_report.meta or {}).get("output_validation")
        if isinstance(ov, dict) and ov.get("ok") is False:
            print(f"OUTPUT_VALIDATION={ov}")

    if not args.evidence_strict:
        # 兜底：真实模型可能“跳过写报告”或输出到非预期路径。
        report_path = workspace_root / "report.md"
        if not report_path.exists():
            wal_locator = (
                str(result.node_report.events_path)
                if result.node_report is not None and result.node_report.events_path is not None
                else ""
            )
            report_md = "\n".join(
                [
                    "# CI Triage Report",
                    "",
                    "> 注：本报告由 host fallback 生成（模型未按契约落盘 report.md）。",
                    "",
                    "## 目标",
                    "- 复现失败 → 最小修复 → 回归验证 → 输出报告",
                    "",
                    "## 产物",
                    "- app.py",
                    "- test_app.py",
                    "- report.md",
                    "",
                    "## 建议验证命令",
                    "- `python -m pytest -q test_app.py`",
                    "",
                    "## 证据链指针",
                    f"- wal_locator/events_path: {wal_locator or '<see terminal output>'}",
                    "",
                ]
            )
            report_path.write_text(report_md + "\n", encoding="utf-8")
    required = ["app.py", "test_app.py", "report.md"]
    missing = missing_artifacts(workspace_root=workspace_root, required=required)
    if missing:
        print(f"MISSING_ARTIFACTS={missing}")
        return 2 if args.strict else 0
    if args.evidence_strict:
        ov = (result.node_report.meta or {}).get("output_validation") if result.node_report is not None else None
        if not (isinstance(ov, dict) and ov.get("ok") is True):
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
