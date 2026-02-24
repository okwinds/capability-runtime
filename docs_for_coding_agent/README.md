# docs_for_coding_agent（编码智能体教学包）

本目录让编码智能体在**不读全仓库**的情况下快速掌握 agently-skills-runtime 的：
- 能力边界（能做什么 / 不能做什么）
- 最短路径（怎么跑通 / 怎么扩展）
- 质量门禁（怎么写测试、怎么证明“完整完成”）

> 约定：本文档包以 `src/` 与 `tests/` 为“地面真相源”；关键边界与验收以 `docs/context/refactoring-spec.md` 为准。

## 推荐阅读顺序

1. `cheatsheet.md` — 最短闭环（统一 Runtime）
2. `00-mental-model.md` — 心智模型：Protocol → Runtime → Report
3. `contract.md` — 编码任务契约（Spec-Driven + TDD）

补充说明：
- 本目录只维护“最短闭环”三份文档，避免为建设期引入多套叙事与学习面。
- 扩展文档（API 清单 / 组合模式 / 接线指南 / Agent Domain 指南）已归档到 `archive/` 中（追溯入口见 `archive/README.md`）。

## 配套示例

`examples/` 目录包含可运行的渐进式示例：
- 01：最短闭环（mock + bridge）
- 02：Workflow（顺序 + 循环 + 条件）
- 03-04：端到端（真实 LLM + 证据链；TriggerFlow 顶层编排）
- 其余目录为对照材料（不作为主线学习入口）

入口：
- `examples/README.md`

## 协作规则

以 `AGENTS.md` 为准（Spec-Driven + TDD + worklog + 文档索引）。
