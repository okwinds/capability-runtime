from __future__ import annotations

"""
form_interview_pro：面向人类的小 app/MVP（skills-first）。

双模式：
- offline：FakeChatBackend 驱动真实 skills_runtime.Agent loop（可回归）
- real：真模型（OpenAI-compatible，经 Agently requester 作为传输层）
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills_runtime.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall
from skills_runtime.safety.approvals import ApprovalDecision

from agently_skills_runtime import AgentSpec, CapabilityKind, CapabilitySpec, Runtime

from examples.apps._shared.app_support import (
    AutoApprovalProvider,
    build_evidence_strict_output_validator,
    ScriptedApprovalProvider,
    ScriptedHumanIO,
    TerminalApprovalProvider,
    TerminalHumanIO,
    build_bridge_runtime_from_env,
    env_or_default,
    load_env_file,
    missing_artifacts,
    write_overlay_for_app,
)


def _build_offline_backend(*, answers: Dict[str, str]) -> FakeChatBackend:
    """
    构造离线 Fake backend：
    - 先问用户问题
    - 再推进计划、落盘 submission、最小校验、输出 report
    """

    questions = {
        "questions": [
            {"id": "full_name", "header": "姓名", "question": "你的姓名？"},
            {"id": "email", "header": "邮箱", "question": "你的邮箱？"},
            {
                "id": "product",
                "header": "产品",
                "question": "你要预订的产品？",
                "options": [{"label": "产品A"}, {"label": "产品B"}, {"label": "产品C"}],
            },
            {
                "id": "quantity",
                "header": "数量",
                "question": "数量（正整数）？",
                "options": [{"label": "1"}, {"label": "2"}, {"label": "3"}],
            },
        ]
    }

    plan_1 = {
        "explanation": "表单访谈：收集字段",
        "plan": [
            {"step": "收集字段", "status": "in_progress"},
            {"step": "落盘产物", "status": "pending"},
            {"step": "最小校验", "status": "pending"},
        ],
    }
    plan_2 = {
        "explanation": "表单访谈：落盘与校验",
        "plan": [
            {"step": "收集字段", "status": "completed"},
            {"step": "落盘产物", "status": "completed"},
            {"step": "最小校验", "status": "completed"},
        ],
    }

    qa_argv = [
        str(sys.executable),
        "-c",
        "import json; d=json.load(open('submission.json','r',encoding='utf-8')); "
        "assert '@' in d.get('email',''); assert int(d.get('quantity')) >= 1; print('FORM_OK')",
    ]

    submission_json = json.dumps(answers, ensure_ascii=False, indent=2) + "\n"
    report_md = "\n".join(
        [
            "# Form Interview Report",
            "",
            "## 收集字段",
            f"- full_name: {answers.get('full_name')}",
            f"- email: {answers.get('email')}",
            f"- product: {answers.get('product')}",
            f"- quantity: {answers.get('quantity')}",
            "",
            "## 产物",
            "- submission.json",
            "- report.md",
            "",
        ]
    )

    return FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[LlmToolCall(call_id="tc_input", name="request_user_input", args=questions)],
                        finish_reason="tool_calls",
                    ),
                    ChatStreamEvent(type="completed", finish_reason="tool_calls"),
                ]
            ),
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            LlmToolCall(call_id="tc_plan1", name="update_plan", args=plan_1),
                            LlmToolCall(
                                call_id="tc_write_submission",
                                name="file_write",
                                args={"path": "submission.json", "content": submission_json},
                            ),
                            LlmToolCall(
                                call_id="tc_qa",
                                name="shell_exec",
                                args={"argv": qa_argv, "timeout_ms": 5000, "sandbox": "none"},
                            ),
                            LlmToolCall(call_id="tc_plan2", name="update_plan", args=plan_2),
                            LlmToolCall(
                                call_id="tc_write_report",
                                name="file_write",
                                args={"path": "report.md", "content": report_md},
                            ),
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
                id="app.form_interview_pro",
                kind=CapabilityKind.AGENT,
                name="FormInterviewPro",
                description="\n".join(
                    [
                        "你正在运行一个表单访谈应用（MVP）。",
                        "必须使用工具完成：",
                        "- request_user_input（收集字段）",
                        "- update_plan（同步进度）",
                        "- file_write(submission.json)",
                        "- shell_exec（最小确定性校验，例如断言 email/quantity）",
                        "- file_write(report.md)",
                        "要求：skills-first；system prompt 保持薄；角色能力来自 skills。",
                    ]
                ),
            ),
            skills=["form-interviewer", "form-validator", "form-reporter"],
            system_prompt="\n".join(
                [
                    "执行协议（必须严格遵守）：",
                    "A) 若输入中 evidence_strict=true：",
                    "   - 只允许 **一轮** tool_calls，且只能包含以下 3 个调用：",
                    "     1) file_write(submission.json)：content 必须是输入里的 host_submission_json",
                    "     2) shell_exec：args 必须是 {argv:[\"python\",\"validate_input.py\",\"<email>\",\"<quantity>\"], timeout_ms:8000, sandbox:\"none\"}",
                    "        - <email>/<quantity> 必须来自输入字段（email/quantity）",
                    "     3) file_write(report.md)：content 必须是输入里的 host_report_md_template",
                    "   - tool_calls 执行完后：下一条消息只能输出纯文本 `ok`，不得再调用任何工具。",
                    "B) 否则（非 strict）：按以下清单完成，不要跳步：",
                    "   0) 若输入中已包含 full_name/email/product/quantity，则不要 request_user_input，直接进入落盘与校验。",
                    "   1) request_user_input 收集 full_name/email/product/quantity（稳定 id）",
                    "   2) update_plan 标注进度",
                    "   3) file_write 写入 submission.json（合法 JSON）",
                    "   4) shell_exec 做确定性校验（可用 python -c 或 validate_input.py；禁止引用不存在文件）",
                    "   5) file_write 写入 report.md（包含产物清单与最小回归命令）",
                    "   6) 最终输出一行简短确认（例如 ok）",
                ]
            ),
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="form_interview_pro (offline/real)")
    parser.add_argument("--workspace-root", default=".", help="Workspace root path")
    parser.add_argument("--mode", choices=["offline", "real"], default="offline", help="Run mode")
    parser.add_argument(
        "--non-interactive",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Non-interactive mode (auto approvals + scripted answers).",
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

    # 给 real 模式提供一个稳定的“最小确定性校验脚本”（避免模型引用不存在文件）。
    # 说明：
    # - 该脚本是示例场景的固定资产，不依赖外部网络；
    # - 模型可选择用 `python3 validate_input.py <email> <quantity>` 做校验。
    (workspace_root / "validate_input.py").write_text(
        "\n".join(
            [
                "import re",
                "import sys",
                "",
                "def main() -> int:",
                "    if len(sys.argv) != 3:",
                "        print('usage: validate_input.py <email> <quantity>', file=sys.stderr)",
                "        return 2",
                "    email = sys.argv[1].strip()",
                "    qty_raw = sys.argv[2].strip()",
                "    if '@' not in email or not re.match(r'^[^@]+@[^@]+\\.[^@]+$', email):",
                "        print('invalid email', file=sys.stderr)",
                "        return 1",
                "    try:",
                "        qty = int(qty_raw)",
                "    except Exception:",
                "        print('invalid quantity', file=sys.stderr)",
                "        return 1",
                "    if qty < 1:",
                "        print('invalid quantity', file=sys.stderr)",
                "        return 1",
                "    print('FORM_OK')",
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

    app_dir = Path(__file__).resolve().parent
    skills_root = (app_dir / "skills").resolve()

    from agently_skills_runtime.upstream_compat import detect_skills_space_schema

    space_schema = detect_skills_space_schema()
    namespace_for_demo = "examples:apps:form-interview" if space_schema == "namespace" else None

    # overlay 写入 workspace，保证“产物与配置同处一个 workspace”
    overlay = write_overlay_for_app(
        workspace_root=workspace_root,
        skills_root=skills_root,
        max_steps=60,
        safety_mode="ask",
        namespace=namespace_for_demo,
        planner_model=env_or_default("MODEL_NAME", "gpt-4o-mini") if args.mode == "real" else None,
        executor_model=env_or_default("MODEL_NAME", "gpt-4o-mini") if args.mode == "real" else None,
    )

    if namespace_for_demo:
        print(f"namespace={namespace_for_demo}")
        print(f"skill_mentions=$[{namespace_for_demo}].form-interviewer / form-validator / form-reporter")

    if args.mode == "offline":
        answers = {
            "full_name": "张三",
            "email": "zhangsan@example.com",
            "product": "产品A",
            "quantity": "2",
        }
        runtime = build_bridge_runtime_from_env(
            workspace_root=workspace_root,
            overlay=overlay,
            sdk_backend=_build_offline_backend(answers=answers),
            approval_provider=ScriptedApprovalProvider(
                decisions=[
                    ApprovalDecision.APPROVED_FOR_SESSION,  # file_write submission
                    ApprovalDecision.APPROVED_FOR_SESSION,  # shell_exec
                    ApprovalDecision.APPROVED_FOR_SESSION,  # file_write report
                ]
            ),
            human_io=ScriptedHumanIO(answers_by_question_id=answers),
        )
        _register_capability(runtime)
        assert runtime.validate() == []

        result = asyncio.run(runtime.run("app.form_interview_pro", input={}))
        print("EXAMPLE_OK: form_interview_pro")
        if result.node_report and result.node_report.events_path:
            print(f"wal_locator={result.node_report.events_path}")
        return 0

    # real mode
    dotenv_path = app_dir / ".env"
    if dotenv_path.exists():
        load_env_file(dotenv_path)

    try:
        output_validator = None
        output_validation_mode = "off"
        if args.evidence_strict:
            output_validation_mode = "error"
            output_validator = build_evidence_strict_output_validator(
                schema_id="examples.form_interview_pro.evidence_strict.v1",
                require_file_writes=["submission.json", "report.md"],
                require_tools_ok=["shell_exec"],
            )

        runtime = build_bridge_runtime_from_env(
            workspace_root=workspace_root,
            overlay=overlay,
            sdk_backend=None,
            approval_provider=AutoApprovalProvider() if args.non_interactive else TerminalApprovalProvider(),
            human_io=(
                ScriptedHumanIO(
                    {
                        "full_name": "张三",
                        "email": "zhangsan@example.com",
                        "product": "产品A",
                        "quantity": "2",
                    },
                    default_answer="N/A",
                )
                if args.non_interactive
                else TerminalHumanIO()
            ),
            output_validation_mode=output_validation_mode,
            output_validator=output_validator,
        )
    except Exception as exc:
        print("=== form_interview_pro ===")
        print("缺少真实模型配置，已退出（exit code 0）。")
        print("请准备：examples/apps/form_interview_pro/.env")
        print("必需变量：OPENAI_API_KEY / OPENAI_BASE_URL / MODEL_NAME")
        print(f"error={type(exc).__name__}: {exc}")
        return 0
    _register_capability(runtime)
    assert runtime.validate() == []
    run_input = {}
    if args.non_interactive:
        # non-interactive smoke：提供预置输入，避免真实模型反复 request_user_input 进入循环。
        run_input = {
            "full_name": "张三",
            "email": "zhangsan@example.com",
            "product": "产品A",
            "quantity": "2",
        }
    run_input["evidence_strict"] = bool(args.evidence_strict)
    if args.evidence_strict and run_input:
        submission_obj = {
            "full_name": run_input.get("full_name", ""),
            "email": run_input.get("email", ""),
            "product": run_input.get("product", ""),
            "quantity": run_input.get("quantity", ""),
        }
        host_submission_json = json.dumps(submission_obj, ensure_ascii=False, indent=2) + "\n"
        host_report_md_template = "\n".join(
            [
                "# Form Interview Report",
                "",
                "## 输入字段（摘要）",
                f"- full_name: {run_input.get('full_name','')}",
                f"- email: {run_input.get('email','')}",
                f"- product: {run_input.get('product','')}",
                f"- quantity: {run_input.get('quantity','')}",
                "",
                "## 产物",
                "- submission.json",
                "- report.md",
                "",
                "## 最小回归命令（离线确定性）",
                "- `python validate_input.py <email> <quantity>`",
                "",
                "## 证据链指针",
                "- wal_locator/events_path: <see terminal output>",
                "",
            ]
        )
        run_input["host_submission_json"] = host_submission_json
        run_input["host_report_md_template"] = host_report_md_template

    result = asyncio.run(runtime.run("app.form_interview_pro", input=run_input))
    print("\n[final_output]\n")
    print(result.output)
    if result.node_report and result.node_report.events_path:
        print(f"\nwal_locator={result.node_report.events_path}")

    if result.node_report is not None:
        ov = (result.node_report.meta or {}).get("output_validation")
        if isinstance(ov, dict) and ov.get("ok") is False:
            print(f"OUTPUT_VALIDATION={ov}")

    if not args.evidence_strict:
        # 兜底：真实模型在不同供应商/模型下可能不稳定地产生 report.md。
        # 为保证“像小 app 一样跑起来”的最小体验，这里做 fail-soft fallback：
        # - 若缺失 submission.json 且已具备输入字段，则由宿主生成最小 submission；
        # - 若缺失 report.md，则由宿主根据 submission.json 生成最小报告；
        # - 报告中显式标注为 host fallback（避免误以为是模型产物）。
        submission_path = workspace_root / "submission.json"
        if (not submission_path.exists()) and all(
            [
                str(run_input.get("full_name") or "").strip(),
                str(run_input.get("email") or "").strip(),
                str(run_input.get("product") or "").strip(),
                str(run_input.get("quantity") or "").strip(),
            ]
        ):
            submission_obj = {
                "full_name": str(run_input.get("full_name") or ""),
                "email": str(run_input.get("email") or ""),
                "product": str(run_input.get("product") or ""),
                "quantity": str(run_input.get("quantity") or ""),
            }
            submission_path.write_text(json.dumps(submission_obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        report_path = workspace_root / "report.md"
        if not report_path.exists() and submission_path.exists():
            wal_locator = (
                str(result.node_report.events_path)
                if result.node_report is not None and result.node_report.events_path is not None
                else ""
            )
            try:
                submission = json.loads(submission_path.read_text(encoding="utf-8"))
            except Exception:
                submission = {}
            report_md = "\n".join(
                [
                    "# Form Interview Report",
                    "",
                    "> 注：本报告由 host fallback 生成（模型未按契约落盘 report.md；submission.json 也可能由 host 兜底）。",
                    "",
                    "## 收集字段（摘要）",
                    f"- full_name: {submission.get('full_name','')}",
                    f"- email: {submission.get('email','')}",
                    f"- product: {submission.get('product','')}",
                    f"- quantity: {submission.get('quantity','')}",
                    "",
                    "## 产物",
                    "- submission.json",
                    "- report.md",
                    "",
                    "## 最小回归命令（离线确定性）",
                    "- `python -c \"import json; d=json.load(open('submission.json','r',encoding='utf-8')); assert '@' in d.get('email',''); assert int(d.get('quantity'))>=1; print('FORM_OK')\"`",
                    "",
                    "## 证据链指针",
                    f"- wal_locator/events_path: {wal_locator or '<see terminal output>'}",
                    "",
                ]
            )
            report_path.write_text(report_md + "\n", encoding="utf-8")

    required = ["submission.json", "report.md"]
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
