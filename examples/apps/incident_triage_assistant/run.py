from __future__ import annotations

"""
incident_triage_assistant：面向人类的小 app/MVP（skills-first）。

双模式：
- offline：FakeChatBackend 驱动真实 skills_runtime.Agent loop（可回归）
- real：真模型（OpenAI-compatible，经 Agently requester 作为传输层）
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from skills_runtime.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall
from skills_runtime.safety.approvals import ApprovalDecision

from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec, Runtime

from examples.apps._shared.app_support import (  # noqa: E402
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


def _build_offline_backend(*, incident_log: str, runbook_md: str, report_md: str) -> FakeChatBackend:
    """离线 Fake backend：写日志 → 读日志 → 澄清 → 输出 runbook/report。"""

    questions = {
        "questions": [
            {"id": "symptom", "header": "现象", "question": "用户侧看到的现象是什么？"},
            {"id": "impact", "header": "影响", "question": "影响范围与优先级？（例如：P0/P1）"},
        ]
    }
    plan_1 = {
        "explanation": "排障：读取日志并澄清",
        "plan": [
            {"step": "准备日志", "status": "completed"},
            {"step": "读取日志", "status": "in_progress"},
            {"step": "澄清问题", "status": "pending"},
            {"step": "输出 runbook", "status": "pending"},
        ],
    }
    plan_2 = {
        "explanation": "排障：输出 runbook 与报告",
        "plan": [
            {"step": "准备日志", "status": "completed"},
            {"step": "读取日志", "status": "completed"},
            {"step": "澄清问题", "status": "completed"},
            {"step": "输出 runbook", "status": "completed"},
        ],
    }

    return FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            LlmToolCall(call_id="w_log", name="file_write", args={"path": "incident.log", "content": incident_log}),
                            LlmToolCall(call_id="p1", name="update_plan", args=plan_1),
                        ],
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
                            LlmToolCall(call_id="r1", name="read_file", args={"file_path": "incident.log"}),
                            LlmToolCall(call_id="q1", name="request_user_input", args=questions),
                            LlmToolCall(call_id="p2", name="update_plan", args=plan_2),
                            LlmToolCall(call_id="w_runbook", name="file_write", args={"path": "runbook.md", "content": runbook_md}),
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
                id="app.incident_triage_assistant",
                kind=CapabilityKind.AGENT,
                name="IncidentTriageAssistant",
                description="\n".join(
                    [
                        "你正在运行一个 oncall 排障助手（MVP）。",
                        "必须使用工具完成：",
                        "- read_file(incident.log)",
                        "- request_user_input（结构化澄清）",
                        "- update_plan（同步进度）",
                        "- file_write(runbook.md/report.md)",
                        "输出中应包含 runbook 的可执行步骤与风险提示。",
                    ]
                ),
            ),
            skills=["incident-triager", "runbook-writer", "incident-reporter"],
            system_prompt="\n".join(
                [
                    "执行协议（必须严格遵守）：",
                    "A) 若输入中 evidence_strict=true：",
                    "   - 只允许 **一轮** tool_calls，且只能包含以下 2 个调用：",
                    "     1) file_write(runbook.md)：content 必须是输入里的 host_runbook_md_template",
                    "     2) file_write(report.md)：content 必须是输入里的 host_report_md_template",
                    "   - tool_calls 执行完后：下一条消息只能输出纯文本 `ok`，不得再调用任何工具。",
                    "B) 否则（非 strict）：严格按以下清单完成，不要循环追问：",
                    "   0) 若输入中已包含 symptom/impact/steps_taken，则不要 request_user_input，直接进入产物落盘。",
                    "   1) read_file 读取 incident.log",
                    "   2) 如需澄清：最多一轮 request_user_input（推荐 symptom/impact/steps_taken）",
                    "   3) update_plan 标注进度",
                    "   4) file_write 写出 runbook.md（可执行步骤 + 风险提示）",
                    "   5) file_write 写出 report.md（产物清单 + 最小复现命令 + 证据链指针说明）",
                    "   6) 最终输出一行简短确认（例如 ok）",
                ]
            ),
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="incident_triage_assistant (offline/real)")
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

    # demo 形态：默认提供一份最小 incident.log（若用户未提供）。
    # 真实使用：读者可以自行替换该文件内容，观察 runbook/report 的变化。
    incident_log_path = workspace_root / "incident.log"
    if not incident_log_path.exists():
        incident_log_path.write_text(
            "\n".join(
                [
                    "2026-02-25T00:00:01Z ERROR api timeout: upstream=payments latency_ms=12000",
                    "2026-02-25T00:00:02Z WARN retry exhausted: route=/checkout user=anon",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    app_dir = Path(__file__).resolve().parent
    skills_root = (app_dir / "skills").resolve()

    overlay = write_overlay_for_app(
        workspace_root=workspace_root,
        skills_root=skills_root,
        # strict 模式希望“快速失败/快速完成”，避免在真实模型不稳定时长时间挂起。
        max_steps=30 if args.evidence_strict else 80,
        safety_mode="ask",
        planner_model=env_or_default("MODEL_NAME", "gpt-4o-mini") if args.mode == "real" else None,
        executor_model=env_or_default("MODEL_NAME", "gpt-4o-mini") if args.mode == "real" else None,
    )

    if args.mode == "offline":
        incident_log = "\n".join(
            [
                "2026-02-25T00:00:01Z ERROR api timeout: upstream=payments latency_ms=12000",
                "2026-02-25T00:00:02Z WARN retry exhausted: route=/checkout user=anon",
                "",
            ]
        )
        runbook_md = "\n".join(
            [
                "# Incident Runbook",
                "",
                "## 可能原因",
                "- 上游 payments 超时/抖动",
                "",
                "## 排查步骤",
                "1. 检查上游健康状态与延迟指标",
                "2. 检查最近 30min 部署/变更",
                "3. 如确认上游问题，启用降级/重试策略",
                "",
            ]
        )
        report_md = "\n".join(
            [
                "# Incident Triage Report",
                "",
                "- input: incident.log",
                "- outputs: runbook.md, report.md",
                "",
            ]
        )

        runtime = build_bridge_runtime_from_env(
            workspace_root=workspace_root,
            overlay=overlay,
            sdk_backend=_build_offline_backend(incident_log=incident_log, runbook_md=runbook_md, report_md=report_md),
            approval_provider=ScriptedApprovalProvider(
                decisions=[
                    ApprovalDecision.APPROVED_FOR_SESSION,  # file_write incident.log
                    ApprovalDecision.APPROVED_FOR_SESSION,  # file_write runbook
                    ApprovalDecision.APPROVED_FOR_SESSION,  # file_write report
                ]
            ),
            human_io=ScriptedHumanIO(answers_by_question_id={"symptom": "结账超时", "impact": "P0"}),
        )
        _register_capability(runtime)
        assert runtime.validate() == []
        result = asyncio.run(runtime.run("app.incident_triage_assistant", input={}))
        print("EXAMPLE_OK: incident_triage_assistant")
        if result.node_report and result.node_report.events_path:
            print(f"wal_locator={result.node_report.events_path}")
        return 0

    dotenv_path = app_dir / ".env"
    if dotenv_path.exists():
        load_env_file(dotenv_path)

    try:
        output_validator = None
        output_validation_mode = "off"
        if args.evidence_strict:
            output_validation_mode = "error"
            output_validator = build_evidence_strict_output_validator(
                schema_id="examples.incident_triage_assistant.evidence_strict.v1",
                require_file_writes=["runbook.md", "report.md"],
                require_tools_ok=[],
            )

        runtime = build_bridge_runtime_from_env(
            workspace_root=workspace_root,
            overlay=overlay,
            sdk_backend=None,
            approval_provider=AutoApprovalProvider() if args.non_interactive else TerminalApprovalProvider(),
            human_io=(
                ScriptedHumanIO(
                    {
                        # 兼容离线/real 可能出现的不同 question_id（best-effort）。
                        "symptom": "结账超时",
                        "impact": "P0",
                        "clarification": "是，影响结账路径（/checkout），P0。",
                        "user_action": "匿名用户点击“结账/支付”按钮后转圈超时。",
                        "steps_taken": "已重试多次；查看 payments 延迟；准备启用降级/熔断；暂未回滚。",
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
        print("=== incident_triage_assistant ===")
        print("缺少真实模型配置，已退出（exit code 0）。")
        print("请准备：examples/apps/incident_triage_assistant/.env")
        print("必需变量：OPENAI_API_KEY / OPENAI_BASE_URL / MODEL_NAME")
        print(f"error={type(exc).__name__}: {exc}")
        return 0

    _register_capability(runtime)
    assert runtime.validate() == []
    run_input = {}
    if args.non_interactive:
        run_input = {
            "symptom": "结账超时",
            "impact": "P0",
            "steps_taken": "已重试多次；查看 payments 延迟；准备启用降级/熔断；暂未回滚。",
        }
    run_input["evidence_strict"] = bool(args.evidence_strict)
    if args.evidence_strict:
        host_runbook_md_template = "\n".join(
            [
                "# Incident Runbook",
                "",
                "## 目标",
                "- 提供可执行的排障步骤与风险提示",
                "",
                "## 排查步骤（示例）",
                "1. 检查上游依赖健康状态与延迟指标",
                "2. 检查最近 30min 部署/变更",
                "3. 若确认上游问题：启用降级/熔断/限流策略",
                "",
                "## 风险提示",
                "- 避免在未评估影响范围前进行不可逆操作",
                "",
            ]
        )
        host_report_md_template = "\n".join(
            [
                "# Incident Triage Report",
                "",
                "## 产物",
                "- incident.log",
                "- runbook.md",
                "- report.md",
                "",
                "## 证据链指针",
                "- wal_locator/events_path: <see terminal output>",
                "",
            ]
        )
        run_input["host_runbook_md_template"] = host_runbook_md_template
        run_input["host_report_md_template"] = host_report_md_template

    result = asyncio.run(runtime.run("app.incident_triage_assistant", input=run_input))
    print("\n[final_output]\n")
    print(result.output)
    if result.node_report and result.node_report.events_path:
        print(f"\nwal_locator={result.node_report.events_path}")

    if result.node_report is not None:
        ov = (result.node_report.meta or {}).get("output_validation")
        if isinstance(ov, dict) and ov.get("ok") is False:
            print(f"OUTPUT_VALIDATION={ov}")

    if not args.evidence_strict:
        runbook_path = workspace_root / "runbook.md"
        if not runbook_path.exists():
            wal_locator = (
                str(result.node_report.events_path)
                if result.node_report is not None and result.node_report.events_path is not None
                else ""
            )
            incident_excerpt = ""
            try:
                incident_excerpt = (workspace_root / "incident.log").read_text(encoding="utf-8").strip().splitlines()[0][:200]
            except Exception:
                incident_excerpt = ""
            runbook_md = "\n".join(
                [
                    "# Incident Runbook",
                    "",
                    "> 注：本 runbook 由 host fallback 生成（模型未按契约落盘 runbook.md）。",
                    "",
                    "## 现象摘要",
                    f"- first_log_line: {incident_excerpt}",
                    "",
                    "## 快速止血（示例）",
                    "1. 确认影响范围与优先级（P0/P1）",
                    "2. 检查上游依赖健康状态与延迟指标",
                    "3. 如确认上游异常，考虑降级/熔断/回滚到上一版本",
                    "",
                    "## 排查步骤（示例）",
                    "1. 检查错误率/延迟曲线是否突增",
                    "2. 检查最近 30min 部署/配置变更",
                    "3. 对关键依赖（上游服务/数据库/缓存）做健康检查",
                    "4. 若问题持续，准备对外发布公告并升级响应级别",
                    "",
                    "## 证据链指针",
                    f"- wal_locator/events_path: {wal_locator or '<see terminal output>'}",
                    "",
                ]
            )
            runbook_path.write_text(runbook_md + "\n", encoding="utf-8")

    # 兜底：某些真实模型可能在“澄清/工具链路”上不稳定，导致 report.md 未落盘。
    # 为保证示例可复刻运行，这里对 report.md 做 host fallback（显式标注）。
    report_path = workspace_root / "report.md"
    if (not args.evidence_strict) and (not report_path.exists()) and (workspace_root / "runbook.md").exists():
        wal_locator = (
            str(result.node_report.events_path)
            if result.node_report is not None and result.node_report.events_path is not None
            else ""
        )
        report_md = "\n".join(
            [
                "# Incident Triage Report",
                "",
                "> 注：本报告由 host fallback 生成（模型未按契约落盘 report.md）。",
                "",
                "## 输入",
                "- incident.log",
                "",
                "## 产物",
                "- runbook.md",
                "- report.md",
                "",
                "## 最小验证命令（离线确定性）",
                "- `python -c \"print(open('runbook.md','r',encoding='utf-8').read()[:80])\"`",
                "",
                "## 证据链指针",
                f"- wal_locator/events_path: {wal_locator or '<see terminal output>'}",
                "",
            ]
        )
        report_path.write_text(report_md + "\n", encoding="utf-8")

    required = ["runbook.md", "report.md"]
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
