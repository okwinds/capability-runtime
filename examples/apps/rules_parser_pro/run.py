from __future__ import annotations

"""
rules_parser_pro：面向人类的小 app/MVP（skills-first）。

形态：
- 规则（rules.txt）→ 结构化计划（plan.json）→ 确定性执行（result.json）→ 报告（report.md）

双模式：
- offline：FakeChatBackend 驱动真实 skills_runtime.Agent loop（可回归）
- real：真模型（OpenAI-compatible，经 Agently requester 作为传输层）
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

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
    TerminalApprovalProvider,
    TerminalHumanIO,
    build_bridge_runtime_from_env,
    env_or_default,
    load_env_file,
    missing_artifacts,
    write_overlay_for_app,
)


def _deterministic_exec_argv() -> list[str]:
    """
    返回确定性执行命令（shell_exec）。

    说明：
    - 该执行只依赖 plan.json + input.json；
    - 产物 result.json 由脚本在当前工作目录写入。
    """

    code = "\n".join(
        [
            "import json",
            "plan = json.load(open('plan.json', 'r', encoding='utf-8'))",
            "inp = json.load(open('input.json', 'r', encoding='utf-8'))",
            "out = {'version': 1, 'rules_count': len(plan.get('rules', [])), 'labels': []}",
            "for r in plan.get('rules', []):",
            "    if r.get('if') == {'field': 'severity', 'eq': 'high'} and inp.get('severity') == 'high':",
            "        out['labels'].append(str((r.get('then') or {}).get('label')))",
            "json.dump(out, open('result.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)",
            "print('RULES_OK')",
        ]
    )
    return [str(sys.executable), "-c", code]


def _host_parse_rules_to_plan_obj(*, rules_txt: str) -> dict:
    """
    host 侧最小解析：rules.txt -> plan obj。

    说明：
    - 该解析仅覆盖示例中的“简化规则句式”，用于提供稳定 demo 输入；
    - 规则解析的“完整性/DSL 能力”不在本示例范围内（避免过度设计）。

    参数：
    - rules_txt：rules.txt 文件内容（UTF-8 文本）

    返回：
    - plan dict（稳定字段：version/rules[]）
    """

    parsed_rules = []
    pat = re.compile(r"若\\s*(?P<field>[a-zA-Z0-9_]+)\\s*==\\s*(?P<value>[a-zA-Z0-9_]+).*label\\s*=\\s*(?P<label>[a-zA-Z0-9_\\-]+)")
    for line in str(rules_txt).splitlines():
        m = pat.search(line)
        if not m:
            continue
        field = m.group("field")
        value = m.group("value")
        label = m.group("label")
        parsed_rules.append({"id": f"r{len(parsed_rules)+1}", "if": {"field": field, "eq": value}, "then": {"label": label}})

    return {"version": 1, "rules": parsed_rules}


def _build_offline_backend(*, rules_txt: str, plan_obj: dict, input_obj: dict, report_md: str) -> FakeChatBackend:
    """
    构造离线 Fake backend（可回归）。

    工具链路：
    - update_plan（过程感）
    - file_write（rules/input/plan）
    - shell_exec（确定性执行写出 result.json）
    - file_write（report.md）
    """

    plan_1 = {
        "explanation": "规则解析：生成计划并执行",
        "plan": [
            {"step": "写入输入", "status": "in_progress"},
            {"step": "生成 plan.json", "status": "pending"},
            {"step": "确定性执行", "status": "pending"},
            {"step": "输出报告", "status": "pending"},
        ],
    }
    plan_2 = {
        "explanation": "规则解析：完成",
        "plan": [
            {"step": "写入输入", "status": "completed"},
            {"step": "生成 plan.json", "status": "completed"},
            {"step": "确定性执行", "status": "completed"},
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
                            LlmToolCall(call_id="w_rules", name="file_write", args={"path": "rules.txt", "content": rules_txt}),
                            LlmToolCall(
                                call_id="w_input",
                                name="file_write",
                                args={"path": "input.json", "content": json.dumps(input_obj, ensure_ascii=False, indent=2) + "\n"},
                            ),
                            LlmToolCall(
                                call_id="w_plan",
                                name="file_write",
                                args={"path": "plan.json", "content": json.dumps(plan_obj, ensure_ascii=False, indent=2) + "\n"},
                            ),
                            LlmToolCall(
                                call_id="exec",
                                name="shell_exec",
                                args={"argv": _deterministic_exec_argv(), "timeout_ms": 8000, "sandbox": "none"},
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
                id="app.rules_parser_pro",
                kind=CapabilityKind.AGENT,
                name="RulesParserPro",
                description="\n".join(
                    [
                        "你正在运行一个规则解析与确定性执行的小应用（MVP）。",
                        "目标：把规则文本整理为 plan.json，并触发确定性执行产出 result.json 与 report.md。",
                        "必须使用工具完成：",
                        "- 输入优先：若输入中包含 rules_txt/input_json，优先使用它们（避免循环读文件）",
                        "- 否则：read_file(rules.txt/input.json) 读取输入（不要重写）",
                        "- file_write(plan.json)",
                        "- shell_exec（确定性执行：读取 plan.json/input.json，写出 result.json）",
                        "- file_write(report.md)",
                        "要求：skills-first；system prompt 保持薄；角色能力来自 skills。",
                    ]
                ),
            ),
            skills=["rules-planner", "rules-executor", "rules-reporter"],
            system_prompt="\n".join(
                [
                    "执行协议（必须严格遵守）：",
                    "A) 只允许 **一轮** tool_calls，且必须按顺序包含以下 3 个调用：",
                    "   1) file_write(plan.json)：content 必须是输入里的 host_plan_json（必须是合法 JSON；禁止写 YAML）",
                    "   2) shell_exec：argv 必须是 `python deterministic_exec_rules.py`（只生成 result.json；stdout 必须包含 RULES_OK）",
                    "   3) file_write(report.md)：content 必须是输入里的 host_report_md_template",
                    "B) 上述 3 个 tool_calls 执行完成后：下一条消息 **只能输出纯文本 `ok`**，不得再调用任何工具（否则视为失败）。",
                ]
            ),
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="rules_parser_pro (offline/real)")
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
        # strict 模式希望“快速失败/快速完成”，避免在真实模型不稳定时长时间挂起。
        max_steps=40 if args.evidence_strict else 120,
        safety_mode="ask",
        planner_model=env_or_default("MODEL_NAME", "gpt-4o-mini") if args.mode == "real" else None,
        executor_model=env_or_default("MODEL_NAME", "gpt-4o-mini") if args.mode == "real" else None,
    )

    if args.mode == "offline":
        rules_txt = "\n".join(
            [
                "# 规则示例（简化）：",
                "- 若 severity == high，则打标签 label=urgent",
                "",
            ]
        )
        input_obj = {"severity": "high"}
        plan_obj = {
            "version": 1,
            "rules": [
                {"id": "r1", "if": {"field": "severity", "eq": "high"}, "then": {"label": "urgent"}},
            ],
        }
        report_md = "\n".join(
            [
                "# Rules Parser Report",
                "",
                "## 输入",
                "- rules.txt",
                "- input.json",
                "",
                "## 产物",
                "- plan.json",
                "- result.json",
                "- report.md",
                "",
                "## 最小回归命令",
                "- `python -c \"import json; json.load(open('plan.json','r',encoding='utf-8')); json.load(open('result.json','r',encoding='utf-8')); print('OK')\"`",
                "",
            ]
        )

        runtime = build_bridge_runtime_from_env(
            workspace_root=workspace_root,
            overlay=overlay,
            sdk_backend=_build_offline_backend(rules_txt=rules_txt, plan_obj=plan_obj, input_obj=input_obj, report_md=report_md),
            approval_provider=ScriptedApprovalProvider(
                decisions=[
                    ApprovalDecision.APPROVED_FOR_SESSION,  # update_plan (some configs treat as tool)
                    ApprovalDecision.APPROVED_FOR_SESSION,  # file_write rules
                    ApprovalDecision.APPROVED_FOR_SESSION,  # file_write input
                    ApprovalDecision.APPROVED_FOR_SESSION,  # file_write plan
                    ApprovalDecision.APPROVED_FOR_SESSION,  # shell_exec
                    ApprovalDecision.APPROVED_FOR_SESSION,  # update_plan
                    ApprovalDecision.APPROVED_FOR_SESSION,  # file_write report
                ]
            ),
            human_io=None,
        )
        _register_capability(runtime)
        assert runtime.validate() == []
        result = asyncio.run(runtime.run("app.rules_parser_pro", input={}))
        print("EXAMPLE_OK: rules_parser_pro")
        if result.node_report and result.node_report.events_path:
            print(f"wal_locator={result.node_report.events_path}")
        return 0

    dotenv_path = app_dir / ".env"
    if dotenv_path.exists():
        load_env_file(dotenv_path)

    # real demo：提供最小输入（若用户未提供），以便模型聚焦 plan/result 的能力链路。
    rules_path = workspace_root / "rules.txt"
    input_path = workspace_root / "input.json"
    if not rules_path.exists():
        rules_path.write_text(
            "\n".join(
                [
                    "# 规则示例（简化）：",
                    "- 若 severity == high，则打标签 label=urgent",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    if not input_path.exists():
        input_path.write_text(json.dumps({"severity": "high"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # real demo：提供一个确定性执行器脚本，减少模型在 shell_exec 的自由度（更可复刻）。
    # 说明：
    # - 脚本只依赖 plan.json + input.json；
    # - 产物 result.json 由脚本写入当前工作目录（workspace_root）；
    # - 打印 RULES_OK 便于在 WAL 中快速定位执行证据。
    exec_script_path = workspace_root / "deterministic_exec_rules.py"
    if not exec_script_path.exists():
        exec_script_path.write_text(
            "\n".join(
                [
                    "import json",
                    "import sys",
                    "",
                    "",
                    "def main() -> int:",
                    "    try:",
                    "        plan = json.load(open('plan.json', 'r', encoding='utf-8'))",
                    "        inp = json.load(open('input.json', 'r', encoding='utf-8'))",
                    "    except Exception as exc:",
                    "        print(f'failed to load inputs: {type(exc).__name__}', file=sys.stderr)",
                    "        return 2",
                    "",
                    "    labels = []",
                    "    for r in plan.get('rules', []):",
                    "        cond = r.get('if') or {}",
                    "        then = r.get('then') or {}",
                    "        field = cond.get('field')",
                    "        eq = cond.get('eq')",
                    "        if field is None:",
                    "            continue",
                    "        if str(inp.get(str(field), '')) == str(eq):",
                    "            labels.append(str(then.get('label')))",
                    "",
                    "    out = {'version': 1, 'rules_count': len(plan.get('rules', [])), 'labels': labels}",
                    "    json.dump(out, open('result.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)",
                    "    print('RULES_OK')",
                    "    return 0",
                    "",
                    "",
                    "if __name__ == '__main__':",
                    "    raise SystemExit(main())",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    try:
        output_validator = None
        output_validation_mode = "off"
        if args.evidence_strict:
            output_validation_mode = "error"
            output_validator = build_evidence_strict_output_validator(
                schema_id="examples.rules_parser_pro.evidence_strict.v1",
                require_file_writes=["plan.json", "report.md"],
                require_tools_ok=["shell_exec"],
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
        print("=== rules_parser_pro ===")
        print("缺少真实模型配置，已退出（exit code 0）。")
        print("请准备：examples/apps/rules_parser_pro/.env")
        print("必需变量：OPENAI_API_KEY / OPENAI_BASE_URL / MODEL_NAME")
        print(f"error={type(exc).__name__}: {exc}")
        return 0

    _register_capability(runtime)
    assert runtime.validate() == []
    rules_txt = rules_path.read_text(encoding="utf-8")
    input_json = input_path.read_text(encoding="utf-8")
    host_plan_obj = _host_parse_rules_to_plan_obj(rules_txt=rules_txt)
    host_plan_json = json.dumps(host_plan_obj, ensure_ascii=False, indent=2) + "\n"
    host_report_md_template = "\n".join(
        [
            "# Rules Parser Report",
            "",
            "## 输入",
            "- rules.txt",
            "- input.json",
            "",
            "## 产物",
            "- plan.json",
            "- result.json",
            "- report.md",
            "",
            "## 最小回归命令（离线确定性）",
            "- `python deterministic_exec_rules.py`",
            "",
            "## 证据链指针",
            "- wal_locator/events_path: <see terminal output>",
            "",
        ]
    )
    result = asyncio.run(
        runtime.run(
            "app.rules_parser_pro",
            input={
                "evidence_strict": bool(args.evidence_strict),
                "rules_txt": rules_txt,
                "input_json": input_json,
                "host_plan_json": host_plan_json,
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

    # 兜底：真实模型在“生成 plan + 触发确定性执行”上可能不稳定，导致关键产物缺失。
    # 为保证示例作为“小 app/MVP”可复刻，这里对 plan/result/report 做 host fallback：
    # - 仅在对应文件缺失时触发；
    # - 输出明确标注为 fallback（避免与模型产物混淆）。
    # evidence-strict 下必须禁用 fallback（用工具证据链做门禁）。
    def _host_fallback_rules_to_plan_and_result() -> None:
        """
        将 rules.txt + input.json 做一次最小可复刻的解析与执行（host fallback）。

        说明：
        - 仅覆盖示例中“简化规则句式”（用于演示形态，不追求完整 DSL）；
        - 若无法解析规则，则生成空 rules 列表（仍可保证产物存在）。
        """

        rules_txt = (workspace_root / "rules.txt").read_text(encoding="utf-8") if (workspace_root / "rules.txt").exists() else ""
        try:
            inp = json.loads((workspace_root / "input.json").read_text(encoding="utf-8"))
        except Exception:
            inp = {}

        parsed_rules = []
        # 支持形态：- 若 severity == high，则打标签 label=urgent
        pat = re.compile(r"若\\s*(?P<field>[a-zA-Z0-9_]+)\\s*==\\s*(?P<value>[a-zA-Z0-9_]+).*label\\s*=\\s*(?P<label>[a-zA-Z0-9_\\-]+)")
        for line in rules_txt.splitlines():
            m = pat.search(line)
            if not m:
                continue
            field = m.group("field")
            value = m.group("value")
            label = m.group("label")
            parsed_rules.append({"id": f"r{len(parsed_rules)+1}", "if": {"field": field, "eq": value}, "then": {"label": label}})

        plan_obj = {"version": 1, "rules": parsed_rules}
        (workspace_root / "plan.json").write_text(json.dumps(plan_obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        labels = []
        for r in parsed_rules:
            cond = r.get("if") or {}
            then = r.get("then") or {}
            field = cond.get("field")
            eq = cond.get("eq")
            if field is not None and str(inp.get(str(field), "")) == str(eq):
                labels.append(str(then.get("label")))
        out = {"version": 1, "rules_count": len(parsed_rules), "labels": labels}
        (workspace_root / "result.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if (not args.evidence_strict) and (
        not (workspace_root / "plan.json").exists() or not (workspace_root / "result.json").exists()
    ):
        _host_fallback_rules_to_plan_and_result()

    report_path = workspace_root / "report.md"
    if (not args.evidence_strict) and (not report_path.exists()):
        wal_locator = (
            str(result.node_report.events_path)
            if result.node_report is not None and result.node_report.events_path is not None
            else ""
        )
        report_md = "\n".join(
            [
                "# Rules Parser Report",
                "",
                "> 注：本报告由 host fallback 生成（模型未按契约落盘 report.md）。",
                "",
                "## 输入",
                "- rules.txt",
                "- input.json",
                "",
                "## 产物",
                "- plan.json",
                "- result.json",
                "- report.md",
                "",
                "## 最小回归命令（离线确定性）",
                "- `python -c \"import json; json.load(open('plan.json','r',encoding='utf-8')); json.load(open('result.json','r',encoding='utf-8')); print('OK')\"`",
                "",
                "## 证据链指针",
                f"- wal_locator/events_path: {wal_locator or '<see terminal output>'}",
                "",
            ]
        )
        report_path.write_text(report_md + "\n", encoding="utf-8")
    required = ["plan.json", "result.json", "report.md"]
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
