# docs_for_coding_agent（编码智能体教学包）

本目录让编码智能体在**不读全仓库**的情况下快速掌握 capability-runtime 的：
- 能力边界（能做什么 / 不能做什么）
- 最短路径（怎么跑通 / 怎么扩展）
- 质量门禁（怎么写测试、怎么证明“完整完成”）

> 约定：本文档包的阅读入口以 `DOCS_INDEX.md` 为准；源规格以 `docs/specs/` 为门禁依据；`openspec/specs/` 为归档镜像用于对照。验收与取证以离线回归测试、运行事件与 worklog 记录为准。`docs/context/refactoring-spec.md` 属于过程材料，仅用于追溯。

## 推荐阅读顺序

1. `cheatsheet.md` — 最短闭环（统一 Runtime）
2. `00-mental-model.md` — 心智模型：Protocol → Runtime → Report
3. `contract.md` — 编码任务契约（Spec-Driven + TDD）
4. `capability-coverage-map.md` — 能力覆盖矩阵（无死角验收基线）
5. `examples/README.md` — 可回归示例库（atomic + recipes）

补充说明：
- 本目录只维护“最短闭环”主线文档（上表 1~4）+ 示例入口（第 5 项），避免为建设期引入多套叙事与学习面。
- 扩展文档（API 清单 / 组合模式 / 接线指南 / Agent Domain 指南）已归档到仓库根目录 `archive/` 中（追溯入口见 `archive/README.md`）。

## 配套示例

仓库根目录 `examples/` 包含可运行的渐进式示例：
- 01：最短闭环（mock + bridge）
- 02：Workflow（顺序 + 循环 + 条件）
- 03-04：端到端（真实 LLM + 证据链；TriggerFlow 顶层编排）
- 其余目录为对照材料（不作为主线学习入口）

入口：
- `examples/README.md`

## 本变更新增：可回归教学示例库（atomic + recipes）

为让编码智能体通过小样本学习掌握“如何用本框架组织能力并落地代码”，新增：
- `docs_for_coding_agent/examples/atomic/`：原子示例（每例只教 1 个能力点）
- `docs_for_coding_agent/examples/recipes/`：组合配方（面向真实交付形态）

入口：
- `docs_for_coding_agent/examples/README.md`

## 协作规则

以 `AGENTS.md` 为准（Spec-Driven + TDD + worklog + 文档索引）。
