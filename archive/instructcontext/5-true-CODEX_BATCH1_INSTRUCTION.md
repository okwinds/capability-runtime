# BATCH 1 指令：cheatsheet + 基础能力示例（01-05）

> **前置条件**：编码智能体必须先读完 `CODEX_CONTEXT_BRIEF.md`。
>
> **目标**：生成"最小可用教学包"——一份 cheatsheet 和 5 个基础示例，
> 覆盖框架最核心的声明→注册→执行→编排模式。
>
> **交付后验证**：所有 run.py 必须可独立运行，且 `python -m pytest tests/ -v` 继续通过。

---

## 产出 1：`docs_for_coding_agent/cheatsheet.md`

### 要求

- 面向编码智能体，语言精练，代码优先
- 总长度 200-300 行
- 包含以下章节（按此顺序）：

```markdown
# agently-skills-runtime Cheatsheet

## 0) 核心共识
- 三元对等：Skill / Agent / Workflow 是对等的能力原语
- 互嵌可组合：三者可以互相嵌套
- 标准流程：声明 → 注册 → 校验 → 执行

## 1) 最短路径：10 行代码跑通第一个 Agent
（给出完整的可复制粘贴代码，使用 mock adapter）
（代码必须基于种子代码 A 改写，但更简洁）

## 2) 核心 import 速查
（列出所有公共 API 的 import 路径，按 Protocol/Runtime/Adapters 分组）

## 3) 五种 Workflow 编排模式
### 顺序执行 (Step)
（3-5 行核心代码片段 + 一句话说明）
### 循环编排 (LoopStep)
（3-5 行核心代码片段 + 一句话说明 + iterate_over 用法）
### 并行编排 (ParallelStep)
（3-5 行核心代码片段）
### 条件分支 (ConditionalStep)
（3-5 行核心代码片段）
### 嵌套 Workflow
（3-5 行核心代码片段）

## 4) InputMapping 6 种 source 前缀
（表格形式，每种一行示例）

## 5) 安全护栏
（递归深度 / 循环上限 / 全局熔断 的默认值和配置方法）

## 6) 常见错误
- ❌ 忘记 validate() → 运行时 "Capability not found"
- ❌ LoopStep 的 iterate_over 指向非列表 → 运行时错误
- ❌ InputMapping source 前缀拼写错误 → 静默得到 None
- ❌ 忘记设置 loop_compatible=True → 框架不会阻止但语义不清
```

---

## 产出 2：`docs_for_coding_agent/README.md`

### 要求

- 说明这个目录是什么、面向谁、怎么用
- 推荐阅读顺序
- 链接到 cheatsheet、后续文档（占位即可）、examples/

### 结构模板

```markdown
# docs_for_coding_agent（编码智能体教学包）

本目录让编码智能体在**不读全仓库**的情况下快速掌握 agently-skills-runtime 的：
- 能力边界（能做什么 / 不能做什么）
- 最短路径（怎么跑通 / 怎么扩展）
- 质量门禁（怎么写测试、怎么证明"完整完成"）

## 推荐阅读顺序

1. `cheatsheet.md` — 10 分钟建立核心心智模型
2. `00-mental-model.md` — 深入理解面向能力范式（BATCH 2 交付）
3. `01-capability-inventory.md` — 全 API 清单（BATCH 2 交付）
4. `02-patterns.md` — 6 种典型组合模式详解（BATCH 3 交付）
5. `03-bridge-wiring.md` — 接线真实 LLM（BATCH 3 交付）
6. `04-agent-domain-guide.md` — 从 0 构建业务域（BATCH 4 交付）

## 配套示例

`examples/` 目录包含可运行的渐进式示例：
- 01-05：基础能力（声明 / 顺序 / 循环 / 并行 / 条件）
- 06-08：进阶组合（Skill 注入 / Skill 调度 / 嵌套）
- 09-10：完整场景 + 真实 LLM 接线
- 11：业务域脚手架

## 协作规则

以 `AGENTS.md` 为准。
```

---

## 产出 3：`examples/README.md`

### 要求

```markdown
# agently-skills-runtime Examples

渐进式示例库。每个目录独立可运行。

## 快速开始

pip install -e ".[dev]"
python examples/01_declare_and_run/run.py

## 示例索引

| # | 目录 | 演示内容 | 需要 LLM |
|---|------|---------|---------|
| 01 | 01_declare_and_run | 最小 AgentSpec 声明 + mock 执行 | ❌ |
| 02 | 02_workflow_sequential | 3 个 Agent 顺序执行 + InputMapping | ❌ |
| 03 | 03_workflow_loop | LoopStep：对列表中每个元素调用 Agent | ❌ |
| 04 | 04_workflow_parallel | ParallelStep：多个 Agent 并行执行 | ❌ |
| 05 | 05_workflow_conditional | ConditionalStep：条件分支 | ❌ |
| 06 | 06_skill_injection | Skill 注入 Agent（BATCH 2） | ❌ |
| 07 | 07_skill_dispatch | Skill dispatch_rules 调度（BATCH 2） | ❌ |
| 08 | 08_nested_workflow | Workflow 嵌套 Workflow（BATCH 2） | ❌ |
| 09 | 09_full_scenario_mock | 完整场景模拟（BATCH 3） | ❌ |
| 10 | 10_bridge_wiring | 真实 LLM 接线（BATCH 3） | ✅ |
| 11 | 11_agent_domain_starter | 业务域脚手架（BATCH 4） | ✅ |
```

---

## 产出 4-8：examples/01 ~ examples/05

### 4. `examples/01_declare_and_run/`

**演示**：最小的 AgentSpec 声明 + mock 执行，展示"声明→注册→校验→执行"完整流程。

**README.md 内容要点**：
- 这是什么：框架的 Hello World
- 前置条件：`pip install -e ".[dev]"`
- 运行方法：`python examples/01_declare_and_run/run.py`
- 学到什么：CapabilitySpec, AgentSpec, CapabilityRuntime, MockAdapter 模式

**run.py 要求**：
- 基于种子代码 A 改写
- 声明 2 个不同的 AgentSpec（一个 greeter、一个 calculator），展示同一 Runtime 管理多个能力
- mock adapter 根据 spec.base.id 返回不同结果
- 打印每次执行的 result.status 和 result.output
- 文件开头有完整 docstring
- 总长度 60-80 行

---

### 5. `examples/02_workflow_sequential/`

**演示**：3 个 Agent 顺序执行，展示 Step + InputMapping 数据流。

**场景设计**（通用，不涉及业务）：
- Agent A "idea_generator"：输入 topic → 输出 {"ideas": ["idea1", "idea2", "idea3"]}
- Agent B "idea_evaluator"：输入 ideas → 输出 {"best_idea": "idea2", "score": 85}
- Agent C "report_writer"：输入 best_idea + score → 输出 {"report": "..."}
- Workflow：A → B → C，通过 InputMapping 传递数据

**run.py 要求**：
- 展示 InputMapping 的 `context.`、`previous.`、`step.X.Y` 三种用法
- mock adapter 根据 agent_id 返回不同结果
- 打印每一步的输出
- 总长度 80-120 行

---

### 6. `examples/03_workflow_loop/`

**演示**：LoopStep 对列表中的每个元素调用同一个 Agent。

**场景设计**：
- Agent A "list_generator"：输入 category → 输出 {"items": [{"name": "x"}, {"name": "y"}, {"name": "z"}]}
- Agent B "item_processor"：输入 item_name → 输出 {"processed": "x → PROCESSED"}
- Workflow：A → LoopStep(B, iterate_over="step.generate.items")

**run.py 要求**：
- 展示 LoopStep 的 iterate_over + item_input_mappings 用法
- 展示 `item.name` 前缀的使用
- 展示 collect_as 的默认行为（结果收集为列表）
- 打印循环的每个结果
- 总长度 80-120 行

---

### 7. `examples/04_workflow_parallel/`

**演示**：ParallelStep 让多个 Agent 并行执行。

**场景设计**：
- Agent A "analyzer_alpha"：输入 data → 输出 {"analysis": "alpha perspective"}
- Agent B "analyzer_beta"：输入 data → 输出 {"analysis": "beta perspective"}
- Agent C "analyzer_gamma"：输入 data → 输出 {"analysis": "gamma perspective"}
- Agent D "synthesizer"：输入 3 个分析结果 → 输出综合报告
- Workflow：ParallelStep([A, B, C]) → D

**run.py 要求**：
- 展示 ParallelStep 的 branches 和 join_strategy
- 展示并行步骤的输出如何被后续步骤通过 step.{branch_id} 引用
- 总长度 80-120 行

---

### 8. `examples/05_workflow_conditional/`

**演示**：ConditionalStep 根据上一步输出选择不同分支。

**场景设计**：
- Agent A "classifier"：输入 text → 输出 {"category": "positive" 或 "negative" 或 "neutral"}
- Agent B "positive_handler"：输入 text → 输出 {"action": "celebrate!"}
- Agent C "negative_handler"：输入 text → 输出 {"action": "investigate..."}
- Agent D "neutral_handler"（default）：输入 text → 输出 {"action": "monitor"}
- Workflow：A → ConditionalStep(condition_source="step.classify.category", branches=...)

**run.py 要求**：
- 展示 ConditionalStep 的 condition_source + branches + default
- 运行两次，分别触发不同分支，打印走了哪条路径
- 总长度 80-120 行

---

## 关键约束（对编码智能体的硬要求）

1. **所有示例必须离线可运行** — 不需要真实 LLM，不需要网络
2. **不包含任何业务词汇** — 不出现"漫剧""选题""分镜""角色""剧本"等
3. **每个 run.py 文件开头必须有 docstring** — 说明"这个示例演示什么"
4. **使用 asyncio.run(main())** — 统一异步入口
5. **打印执行结果** — 每个示例运行后有可读的控制台输出
6. **mock adapter 不要太简单** — 应该模拟真实的数据流转（不同 agent_id 返回不同结构的输出）
7. **代码风格**：`from __future__ import annotations`，完整类型注解

---

## 交付清单

完成以下文件后，本 BATCH 即视为交付：

```
docs_for_coding_agent/
├── README.md                          ✅
└── cheatsheet.md                      ✅

examples/
├── README.md                          ✅
├── 01_declare_and_run/
│   ├── README.md                      ✅
│   └── run.py                         ✅
├── 02_workflow_sequential/
│   ├── README.md                      ✅
│   └── run.py                         ✅
├── 03_workflow_loop/
│   ├── README.md                      ✅
│   └── run.py                         ✅
├── 04_workflow_parallel/
│   ├── README.md                      ✅
│   └── run.py                         ✅
└── 05_workflow_conditional/
    ├── README.md                      ✅
    └── run.py                         ✅
```

**验证**：
```bash
# 每个示例可独立运行
python examples/01_declare_and_run/run.py
python examples/02_workflow_sequential/run.py
python examples/03_workflow_loop/run.py
python examples/04_workflow_parallel/run.py
python examples/05_workflow_conditional/run.py

# 既有测试不受影响
python -m pytest tests/ -v
```
