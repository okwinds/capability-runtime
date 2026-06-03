# examples（可运行示例）

本目录包含两类示例资产：
- **渐进式示例（01~05）**：展示本仓统一 `Runtime` 的核心用法（从 mock 到 bridge/编排）。
- **面向人类的小 app/MVP（`apps/`）**：简陋但体验好，同时支持 `offline/real` 双模式，默认离线可回归。

## 快速开始

```bash
python -m pip install -e ".[dev]"
```

最短闭环（推荐，从统一 Runtime 开始）：

```bash
python examples/01_quickstart/run_mock.py
```

Workflow 示例（离线可跑）：

```bash
python examples/02_workflow/run.py
```

## 渐进式示例索引（01~05）

| # | 目录 | 演示内容 | 需要真实 LLM |
|---|------|---------|---------|
| 01 | `01_quickstart/` | 最短闭环：mock + bridge（统一 Runtime） | 部分 ✅ |
| 02 | `02_workflow/` | 顺序 + 循环 + 条件分支（统一 Runtime） | ❌ |
| 03 | `03_bridge_e2e/` | 真实 LLM：tool_call + 自动审批 + NodeReport 证据链 | ✅ |
| 04 | `04_triggerflow_orchestration/` | 通过 `Runtime` / `WorkflowSpec` 观察 runtime workflow lifecycle snapshot | ❌ |
| 05 | `05_workflow_skills_first/` | Workflow 编排 skills-first Agent（离线可回归） | ❌ |
| 05 | `05_dynamic_dag_preview/` | Dynamic DAG preview（runtime-owned plan） | ❌ |
| 06 | `06_responses_bridge/` | Responses requester 显式 opt-in 配置预览 | 可选 |
| 08 | `08_workspace_recall_preview/` | 中立 Workspace/Recall context pack 预览 | ❌ |
| 09 | `09_action_artifact_evidence/` | Action artifact reference evidence 摘要 | ❌ |
| 10 | `10_runtime_bridge_showcase/` | 服务端已配置的 live runtime bridge 展示页 | ✅ |

Capability preview 规则：只使用 `capability_runtime` 契约。Responses 是
opt-in；Dynamic DAG 先编译为 `DynamicWorkflowPlan`。示例不得让下游依赖
upstream-native requester、`TaskDAG`、`DynamicTask`、Workspace、Action 或
TriggerFlow execution 对象。

真实 provider 示例遵循固定接线顺序：先用 gateway 确认模型，再配置 provider
chat transport；只有 `/responses` 可用时才配置 provider responses transport；
随后分别跑 runtime chat 与 runtime responses smoke。runtime 请求模型必须来自
`AgentSpec.llm_config.model`，这样 SDK `ChatRequest.model` 与
`NodeReport.usage.model` 才可审计。chat 与 responses 两条路径都应保留
`NodeReport.usage.request_id` 和 `NodeReport.usage.provider`。

## 人类小应用（apps/）

这些示例更偏“像小 app 一样跑起来”，用于回答：
- 这是什么（框架定位）
- 能做什么（能力边界）
- 怎么用（最短可复刻路径）

统一约定：
- `--mode offline`：离线可回归（默认门禁，不依赖外网/真实 key）
- `--mode real`：真模型可跑（OpenAI-compatible；需要本地 `.env`，仓库只提供 `.env.example`）

索引：

| app | 形态 | 入口 | 说明 |
|---|---|---|---|
| `form_interview_pro` | Terminal | `examples/apps/form_interview_pro/run.py` | 结构化提问→产物→确定性校验 |
| `incident_triage_assistant` | Terminal | `examples/apps/incident_triage_assistant/run.py` | 日志读取→澄清→runbook/report |
| `ci_failure_triage_and_fix` | Terminal | `examples/apps/ci_failure_triage_and_fix/run.py` | pytest fail→apply_patch→pytest ok→report |
| `rules_parser_pro` | Terminal/Batch | `examples/apps/rules_parser_pro/run.py` | rules→plan.json→确定性执行→result.json |
| `sse_gateway_minimal` | HTTP/SSE | `examples/apps/sse_gateway_minimal/run.py` | SSE 事件流→终态结果→wal_locator |
| `ui_events_showcase` | Web UI | `examples/apps/ui_events_showcase/run.py` | UI Events v1：fixtures 回放 + SSE/JSONL + after_id 续传 |

## 对照示例（已归档，非主线）

对照材料已统一归档，不建议作为新项目起点。追溯入口见：
- `archive/README.md`

## 参考应用（非示例）

如需更完整的参考应用/原型（可能依赖真实服务与配置），见：
- `archive/projects/`（已归档，不属于 runtime 主线交付物）

补充说明：
- “mvp studio” 属于下游的 MVP 级示例/集成目标，不属于本仓 runtime 框架主线交付物；如需追溯，请从 `archive/README.md` 进入查找归档入口。
