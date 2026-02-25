# incident_triage_assistant（排障助手 MVP / skills-first）

目标：模拟一次常见 oncall 排障闭环，并保留可审计证据链：
- 读取/分析 incident 日志：`read_file`
- 结构化澄清：`request_user_input`
- 计划同步：`update_plan`
- 输出 runbook + 报告：`file_write`

## 1) 离线运行（默认）

```bash
python examples/apps/incident_triage_assistant/run.py --workspace-root /tmp/asr-app-incident --mode offline
```

预期：
- workspace 下生成：`incident.log`、`runbook.md`、`report.md`、`runtime.yaml`
- 输出中包含 `wal_locator=...`

## 2) 真模型运行（OpenAI-compatible）

```bash
cp examples/apps/incident_triage_assistant/.env.example examples/apps/incident_triage_assistant/.env
python examples/apps/incident_triage_assistant/run.py --workspace-root /tmp/asr-app-incident --mode real
```

说明：
- 真实模式下会要求你在终端回答澄清问题，并在需要时进行审批（ask）。

## 3) 非交互 smoke（用于集成回归/CI）

```bash
python examples/apps/incident_triage_assistant/run.py --workspace-root /tmp/asr-app-incident --mode real --non-interactive
```

说明：
- 若 workspace 下没有 `incident.log`，示例会自动写入一份最小日志（便于开箱即跑）；
- 自动审批 + 预置答案，避免阻塞；
- 默认 `--strict`：若缺失 `runbook.md` / `report.md`，会输出 `MISSING_ARTIFACTS=[...]` 并以 exit code 2 退出。

## 4) evidence-strict（证据严格模式：禁止 host fallback）

```bash
python examples/apps/incident_triage_assistant/run.py \
  --workspace-root /tmp/asr-app-incident \
  --mode real \
  --non-interactive \
  --evidence-strict
```

验收点：
- `runbook.md` 与 `report.md` 必须来自模型的 `file_write` tool evidence（禁用 host fallback）；
- 缺失证据会 fail-closed（exit code 2）。
