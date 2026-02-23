# docs_for_coding_agent（编码智能体教学包）

本目录让编码智能体在**不读全仓库**的情况下快速掌握 agently-skills-runtime 的：
- 能力边界（能做什么 / 不能做什么）
- 最短路径（怎么跑通 / 怎么扩展）
- 质量门禁（怎么写测试、怎么证明“完整完成”）

> 约定：本文档包以 `archive/instructcontext/5-true-CODEX_CONTEXT_BRIEF.md` 为“全局上下文真相源”。  
> 代码层面的“地面真相”以 `src/` 与 `tests/` 为准。

## 推荐阅读顺序

1. `cheatsheet.md` — 10 分钟建立核心心智模型（本批次交付）
2. `00-mental-model.md` — 深入理解面向能力范式（BATCH 2 交付）
3. `01-capability-inventory.md` — 全 API 清单（BATCH 2 交付）
4. `02-patterns.md` — 6 种典型组合模式详解（BATCH 3 交付）
5. `03-bridge-wiring.md` — 接线真实 LLM（BATCH 3 交付）
6. `04-agent-domain-guide.md` — 从 0 构建 Agent Domain（BATCH 4 交付）
7. `contract.md` — 编码任务契约（BATCH 4 交付）

## 配套示例

`examples/` 目录包含可运行的渐进式示例：
- 00：快速体验（离线）
- 01-05：基础能力（声明 / 顺序 / 循环 / 并行 / 条件）
- 06-08：进阶组合（06/07 已迁移为指引；08 为嵌套 Workflow）
- 09-10：完整场景 + 真实 LLM 接线
- 11：Agent Domain 脚手架

入口：
- `examples/README.md`

## 协作规则

以 `AGENTS.md` 为准（Spec-Driven + TDD + worklog + 文档索引）。
