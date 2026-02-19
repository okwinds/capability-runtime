# Engineering Spec v2 Index：agently-skills-runtime（Capability-oriented Runtime）

本目录是 `agently-skills-runtime` 的 **Engineering Spec v2**（能力运行时方向）。

目标：仅凭本文档集（+ 上游依赖可用时的适配器实现），一支具备相关经验的工程团队可以**从零复刻**能力协议、运行时引擎与最小适配器闭环，并通过离线回归与验收标准。

---

## 0) 真相源（Source of Truth）

优先级从高到低：

1. `instructcontext/CODEX_PROMPT.md`（本轮重构的关键真相源）
2. PRD：`docs/prd/agently-skills-runtime-capability-runtime.prd.md`
3. 本目录下 v2 工程规格（本文件及其链接文档）

约束：
- `protocol/` 与 `runtime/` 必须与上游解耦（不依赖上游）。
- `adapters/` 允许依赖上游，但只使用 Public API（不侵入上游、不中断可同步性）。
- 框架不定义人机交互：不引入 approve/review/human interaction 等概念。

---

## 1) 推荐阅读顺序

1. 概览：`00_Overview/SUMMARY.md`
2. 需求矩阵：`00_Overview/REQUIREMENTS_MATRIX.md`
3. 决策记录：`00_Overview/DECISION_LOG.md`
4. 技术栈与可复刻命令：`00_Overview/TECH_STACK.md`
5. 架构与依赖边界：`02_Technical_Design/ARCHITECTURE.md`
6. 公共 API：`02_Technical_Design/PUBLIC_API.md`
7. 数据模型：`02_Technical_Design/DATA_MODEL.md`
8. 错误目录：`02_Technical_Design/ERROR_CATALOG.md`
9. 配置：`04_Operations/CONFIGURATION.md`
10. 测试计划与追溯：`05_Testing/TEST_PLAN.md` + `05_Testing/TRACEABILITY.md`
11. 实施拆解与迁移：`06_Implementation/TASK_BREAKDOWN.md` + `06_Implementation/MIGRATION.md`
12. PRD 校验报告：`00_Overview/PRD_VALIDATION_REPORT.md`

---

## 2) 文档结构

### 00_Overview

- `SUMMARY.md`：项目定位、边界与验收摘要
- `REQUIREMENTS_MATRIX.md`：需求矩阵（FR/NFR + Owner）
- `DECISION_LOG.md`：关键决策与 trade-off
- `TECH_STACK.md`：依赖、版本策略与可复刻命令
- `PRD_VALIDATION_REPORT.md`：按 checklist 校验 PRD 的完整性与假设

### 02_Technical_Design

- `ARCHITECTURE.md`：模块拆分与依赖方向（protocol/runtime 与上游边界）
- `PUBLIC_API.md`：对外导出清单与版本策略
- `DATA_MODEL.md`：dataclass/Enum 的实现级字段清单
- `ERROR_CATALOG.md`：错误类型、抛出场景与处理策略

### 04_Operations

- `CONFIGURATION.md`：RuntimeConfig 字段、默认值与风险

### 05_Testing

- `TEST_PLAN.md`：离线回归命令、范围与门禁
- `TRACEABILITY.md`：需求 → 测试文件映射（计划表，执行阶段补齐）

### 06_Implementation

- `TASK_BREAKDOWN.md`：按 Step 1~6 的 TDD 任务拆解
- `MIGRATION.md`：legacy 归档策略、破坏说明与迁移路径
- `SKILL_INJECTION_POLICY.md`：`SkillSpec.inject_to` 自动注入策略（可回归最小语义）
