# 概览（Summary）

> 文档目标：用最短路径让读者理解“这是什么、边界在哪、如何验收与回归”。

## 1) 项目定位

`agently-skills-runtime`（v0.2.0 方向）是一个 **面向能力（Capability-oriented）** 的运行时框架：

- 统一抽象三种元能力：**Skill / Agent / Workflow**（对等、可嵌套、可组合）。
- 框架职责收敛为三件事：**声明能力 → 执行能力 → 组合能力**。
- 通过适配器桥接上游（Agently、skills-runtime-sdk），但保持 **protocol/runtime 与上游解耦**。

## 2) 边界（必须遵守）

- 框架不包含业务逻辑，不写死特定业务名词/流程/供应商。
- 框架不定义人机交互：不出现 approve/review/human interaction 等概念；业务层自行决定如何消费结果。
- `protocol/` 与 `runtime/` 不依赖上游；上游依赖只允许集中在 `adapters/`。

## 3) 最小可交付形态（v0.2.0）

以 `instructcontext/CODEX_PROMPT.md` 为准，v0.2.0 最小闭环包含：

- 协议层（protocol/）：能力、技能、智能体、工作流、执行上下文。
- 运行时层（runtime/）：注册表、执行引擎、循环控制、执行守卫。
- 适配器层（adapters/）：LLM backend 迁移（保持功能不变）+ 三类能力执行适配器（可先以最小可运行实现落地）。
- 离线回归：覆盖协议解析/递归守卫、registry 依赖校验、workflow loop scenario。

## 4) 验收摘要（摘录）

必须满足（实现阶段门禁）：

1. `pip install -e .` 成功
2. `python -c "from agently_skills_runtime import CapabilityRuntime, SkillSpec, AgentSpec, WorkflowSpec"` 无报错
3. `pytest tests/protocol/` 与 `pytest tests/runtime/` 全部通过
4. 至少 1 个 scenario：Workflow 编排 2 Agent + LoopStep（mock LLM）

## 5) 迁移摘要

- 本轮为破坏式升级（目标版本 v0.2.0）。
- 旧 bridge-only 主入口与旧类型体系整体归档到 `legacy/`（可追溯，但不干扰新主线）。
- `projects/agently-skills-web-prototype/` 保留不动。

