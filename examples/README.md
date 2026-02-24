# agently-skills-runtime Examples

渐进式示例库。每个目录独立可运行。

## 快速开始

```bash
pip install -e ".[dev]"
```

立即可运行（推荐，从统一 Runtime 开始）：

```bash
python examples/01_quickstart/run_mock.py
```

Workflow 示例（离线可跑）：

```bash
python examples/02_workflow/run.py
```

## 示例索引

| # | 目录 | 演示内容 | 需要 LLM |
|---|------|---------|---------|
| 01 | 01_quickstart | 最短闭环：mock + bridge（统一 Runtime） | 部分 ✅ |
| 02 | 02_workflow | 顺序 + 循环 + 条件分支（统一 Runtime） | ❌ |
| 03 | 03_bridge_e2e | 真实 LLM：tool_call + 自动审批 + NodeReport 证据链 | ✅ |
| 04 | 04_triggerflow_orchestration | TriggerFlow 顶层编排多个 Runtime.run()（推荐路径） | ✅ |

## 对照示例（已归档，非主线）

对照材料已统一归档，不建议作为新项目起点。追溯入口见：

- `archive/README.md`

## 参考应用（非示例）

如需更完整的参考应用/原型（可能依赖真实服务与配置），见：

- `archive/projects/`（已归档，不属于 runtime 主线交付物）
