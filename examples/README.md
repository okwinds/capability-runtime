# examples（可运行示例）

本目录包含两类示例资产：
- **渐进式示例（01~04）**：展示本仓统一 `Runtime` 的核心用法（从 mock 到 bridge/编排）。
- **面向人类的小 app/MVP（`apps/`）**：简陋但体验好，同时支持 `offline/real` 双模式，默认离线可回归。

## 快速开始

```bash
pip install -e ".[dev]"
```

最短闭环（推荐，从统一 Runtime 开始）：

```bash
python examples/01_quickstart/run_mock.py
```

Workflow 示例（离线可跑）：

```bash
python examples/02_workflow/run.py
```

## 渐进式示例索引（01~04）

| # | 目录 | 演示内容 | 需要真实 LLM |
|---|------|---------|---------|
| 01 | `01_quickstart/` | 最短闭环：mock + bridge（统一 Runtime） | 部分 ✅ |
| 02 | `02_workflow/` | 顺序 + 循环 + 条件分支（统一 Runtime） | ❌ |
| 03 | `03_bridge_e2e/` | 真实 LLM：tool_call + 自动审批 + NodeReport 证据链 | ✅ |
| 04 | `04_triggerflow_orchestration/` | TriggerFlow 顶层编排多个 `Runtime.run()` | ✅ |

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
| `form_interview_pro` | Terminal | `apps/form_interview_pro/run.py` | 结构化提问→产物→确定性校验 |
| `incident_triage_assistant` | Terminal | `apps/incident_triage_assistant/run.py` | 日志读取→澄清→runbook/report |
| `ci_failure_triage_and_fix` | Terminal | `apps/ci_failure_triage_and_fix/run.py` | pytest fail→apply_patch→pytest ok→report |
| `rules_parser_pro` | Terminal/Batch | `apps/rules_parser_pro/run.py` | rules→plan.json→确定性执行→result.json |
| `sse_gateway_minimal` | HTTP/SSE | `apps/sse_gateway_minimal/run.py` | SSE 事件流→终态结果→wal_locator |

## 对照示例（已归档，非主线）

对照材料已统一归档，不建议作为新项目起点。追溯入口见：
- `archive/README.md`

## 参考应用（非示例）

如需更完整的参考应用/原型（可能依赖真实服务与配置），见：
- `archive/projects/`（已归档，不属于 runtime 主线交付物）
