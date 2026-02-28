# form_interview_pro（表单访谈 MVP / skills-first）

目标：演示一个“像小 app 一样跑起来”的表单访谈闭环，并强调 skills-first + 证据链：
- 结构化提问：`request_user_input`
- 任务推进可见：`update_plan`
- 产物落盘：`file_write`（`submission.json`、`report.md`）
- 最小确定性校验：`shell_exec`（本地断言）
- 证据链：WAL + NodeReport（tool_calls/approvals/activated_skills）

## 1) 离线运行（默认，用于回归）

```bash
python examples/apps/form_interview_pro/run.py --workspace-root /tmp/caprt-app-form --mode offline
```

预期：
- 终端打印关键事件（skill/tool/approval）
- workspace 下生成：
  - `submission.json`
  - `report.md`
  - `runtime.yaml`（overlay）
- 最终输出中包含 wal_locator（NodeReport.events_path）

本示例的 namespace 口径（pinned: `skills-runtime-sdk==0.1.6`）：
- overlay：`skills.spaces[].namespace="examples:apps:form-interview"`（≥3 段）
- strict mention：`$[examples:apps:form-interview].form-interviewer`（同一 namespace 下的多个 skill 同理）

## 2) 真模型运行（OpenAI-compatible）

准备 `.env`（仅本地使用，不入库）：

```bash
cp examples/apps/form_interview_pro/.env.example examples/apps/form_interview_pro/.env
```

编辑 `.env` 填入真实配置后运行：

```bash
python examples/apps/form_interview_pro/run.py --workspace-root /tmp/caprt-app-form --mode real
```

说明：
- 真模型模式下会出现终端交互：
  - 人类输入（表单问题）
  - 审批（高风险工具，如 apply_patch/shell_exec 等；本示例为 ask 模式）

## 3) 非交互 smoke（用于集成回归/CI）

```bash
python examples/apps/form_interview_pro/run.py --workspace-root /tmp/caprt-app-form --mode real --non-interactive
```

说明：
- 自动审批（避免卡在 approvals）；
- 使用预置答案（避免卡在人类输入）；
- 默认 `--strict`：若缺失 `submission.json` / `report.md`，会输出 `MISSING_ARTIFACTS=[...]` 并以 exit code 2 退出。

## 4) evidence-strict（证据严格模式：禁止 host fallback）

```bash
python examples/apps/form_interview_pro/run.py \
  --workspace-root /tmp/caprt-app-form \
  --mode real \
  --non-interactive \
  --evidence-strict
```

验收点：
- `submission.json` 与 `report.md` 必须来自模型的 `file_write` tool evidence（禁用 host fallback）；
- 必须有 `shell_exec` 成功证据（最小确定性校验）；
- 缺失证据会 fail-closed（exit code 2）。
