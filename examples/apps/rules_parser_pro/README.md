# rules_parser_pro（规则→计划→确定性执行 / skills-first）

目标：演示一个“规则驱动的确定性执行”小应用（MVP），让人直观看到：
- 规则（人类可读）如何被整理为 `plan.json`（可审计的中间表示）
- 如何用 **确定性执行**（非 LLM）把 `plan.json + input.json` 转换为 `result.json`
- 全过程保留 WAL + NodeReport 证据链（含 tool_calls / approvals / activated_skills）

## 1) 离线运行（默认，用于回归）

```bash
python examples/apps/rules_parser_pro/run.py --workspace-root /tmp/asr-app-rules --mode offline
```

预期：
- workspace 下生成：
  - `rules.txt`（规则原文）
  - `input.json`（样例输入）
  - `plan.json`（结构化计划）
  - `result.json`（确定性执行结果）
  - `report.md`
  - `runtime.yaml`（overlay）
- 终端输出包含 `wal_locator=...`（NodeReport.events_path）

## 2) 真模型运行（OpenAI-compatible）

准备 `.env`（仅本地使用，不入库）：

```bash
cp examples/apps/rules_parser_pro/.env.example examples/apps/rules_parser_pro/.env
```

运行：

```bash
python examples/apps/rules_parser_pro/run.py --workspace-root /tmp/asr-app-rules --mode real
```

说明：
- 真实模式下会在终端询问你要处理的规则文本（`request_user_input`）；
- 你仍会看到审批（ask），用于展示“确定性执行（shell_exec）”等高风险动作的证据链。

## 3) 非交互 smoke（用于集成回归/CI）

```bash
python examples/apps/rules_parser_pro/run.py --workspace-root /tmp/asr-app-rules --mode real --non-interactive
```

说明：
- 若 workspace 中不存在 `rules.txt/input.json`，示例会写入最小样例输入，便于开箱即跑；
- 自动审批，避免阻塞；
- 默认 `--strict`：若缺失 `plan.json/result.json/report.md`，会输出 `MISSING_ARTIFACTS=[...]` 并以 exit code 2 退出。

## 4) evidence-strict（证据严格模式：禁止 host fallback）

```bash
python examples/apps/rules_parser_pro/run.py \
  --workspace-root /tmp/asr-app-rules \
  --mode real \
  --non-interactive \
  --evidence-strict
```

验收点：
- `plan.json` 与 `report.md` 必须来自模型的 `file_write` tool evidence（禁用 host fallback）；
- 必须有 `shell_exec` 成功证据（运行 `deterministic_exec_rules.py` 生成 `result.json`）；
- 缺失证据会 fail-closed（exit code 2）。
