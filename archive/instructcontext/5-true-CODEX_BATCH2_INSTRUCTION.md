# BATCH 2 指令：心智模型 + 能力清单 + 进阶组合示例（06-08）

> **前置条件**：BATCH 1 已交付并验证通过。
> 编码智能体必须先读完 `CODEX_CONTEXT_BRIEF.md`，
> 并阅读 BATCH 1 已生成的 `docs_for_coding_agent/cheatsheet.md` 和 `examples/01-05`。
>
> **目标**：深入展示"三元对等 + 互嵌可组合"这个核心卖点——
> Skill 如何注入 Agent、Skill 如何调度 Agent/Workflow、Workflow 如何嵌套 Workflow。
>
> **交付后验证**：所有 run.py 可独立运行；`python -m pytest tests/ -v` 继续通过。

---

## 产出 1：`docs_for_coding_agent/00-mental-model.md`

### 要求

- 标题：**面向能力范式：为什么不是 Agent Framework**
- 总长度 150-200 行
- 用**对比法**解释，不用长段落

### 结构模板

```markdown
# 面向能力范式（Capability-Oriented Paradigm）

## 传统 Agent 框架的思路

（2-3 句话总结：大部分框架以 Agent 为中心，Workflow 是 Agent 的调度器，
Skill/Tool 是 Agent 的附属品。三者不对等。）

## 本框架的思路

（2-3 句话总结：Skill/Agent/Workflow 是三种对等的"能力原语"。
它们共享同一个类型基座 CapabilitySpec，通过同一个引擎执行，
通过同一种引用机制 CapabilityRef 互相调用。）

## 对比表

| 维度 | 传统 Agent 框架 | agently-skills-runtime |
|------|----------------|----------------------|
| 核心概念 | Agent | Capability (Skill/Agent/Workflow) |
| 编排方式 | Agent 调用 Agent | 能力调用能力（通过 CapabilityRef） |
| Skill 定位 | Agent 的工具/附件 | 独立能力原语，可反向调度 Agent |
| Workflow 定位 | Agent 的调度器 | 独立能力原语，也可被 Agent/Skill 调度 |
| 嵌套关系 | Agent → Agent | 任意 → 任意（三元互嵌） |
| 类型系统 | 各自定义 | 统一 CapabilitySpec 基座 |

## 三元互嵌图解

（用 ASCII 图展示 Skill ↔ Agent ↔ Workflow 的互相调用关系）
（参考 CODEX_CONTEXT_BRIEF.md 第 4.2 节的图）

## 实际含义

### Skill 不只是"知识文档"
（1-2 句 + 代码片段：SkillSpec.dispatch_rules 可以触发 Agent 执行任务）

### Workflow 不只是"流程图"
（1-2 句 + 代码片段：Workflow 可以被另一个 Workflow 的 step 调用）

### Agent 不只是"LLM 调用者"
（1-2 句 + 代码片段：Agent 可以装载 Skill 来增强能力）

## 何时用哪种原语

| 场景 | 选择 | 理由 |
|------|------|------|
| 封装一段可复用知识/模板 | Skill | 无状态，可注入也可调度 |
| 封装一次 LLM 调用任务 | Agent | 有 prompt、有输入输出 schema |
| 编排多个能力的执行顺序 | Workflow | 有步骤、有数据流、有分支 |
| 以上都可以 | 都行 | 三元对等意味着没有唯一正确答案 |
```

---

## 产出 2：`docs_for_coding_agent/01-capability-inventory.md`

### 要求

- 标题：**能力清单：全部公共类型与 API**
- 这是一份**API 参考速查**，不是教程
- 按 Protocol → Runtime → Adapters 三层组织
- 每个类型列出：名称、所在模块、字段列表（含类型和默认值）、一句话说明
- 总长度 200-300 行

### 结构模板

```markdown
# 能力清单（Capability Inventory）

## Protocol 层

### CapabilitySpec
- 模块：`agently_skills_runtime.protocol.capability`
- 字段：
  - id: str — 唯一标识
  - kind: CapabilityKind — SKILL | AGENT | WORKFLOW
  - name: str = "" — 人类可读名称
  - description: str = "" — 描述
  - tags: List[str] = [] — 标签
  - metadata: Dict[str, Any] = {} — 自定义元数据

### CapabilityKind
- 枚举值：SKILL, AGENT, WORKFLOW

### CapabilityRef
（同上格式...）

### CapabilityResult
（同上格式，特别列出 status, output, error, metadata, duration_ms, report）

### CapabilityStatus
（枚举值 + 说明）

### SkillSpec
（同上格式，特别列出 dispatch_rules, inject_to）

### SkillDispatchRule
（trigger + target）

### AgentSpec
（同上格式，特别列出 skills, tools, prompt_template, system_prompt,
  output_schema, loop_compatible, io_schema）

### WorkflowSpec
（steps, context_schema, output_mappings）

### Step / LoopStep / ParallelStep / ConditionalStep
（每种列出所有字段）

### InputMapping
（source + target_field）

### ExecutionContext
（run_id, bag, step_outputs, call_chain, depth, max_depth + child() 方法 + resolve_mapping() 方法）

## Runtime 层

### RuntimeConfig
（max_depth, max_total_loop_iterations, default_loop_max_iterations）

### AdapterProtocol
（execute 方法签名）

### CapabilityRuntime
（set_adapter, register, register_many, validate, run — 每个方法的签名和一句话说明）

### CapabilityRegistry
（register, get, validate_dependencies）

### ExecutionGuards
（max_total_loop_iterations, check_and_increment, reset）

### LoopController
（run_loop 签名 + fail_strategy 说明）

## Adapters 层

### AgentAdapter
（构造参数 runner 的签名）

### WorkflowAdapter
（无构造参数；execute 内部自动编排 steps）

### SkillAdapter
（加载 source + 处理 dispatch_rules + 处理 inject_to）
```

---

## 产出 3：`examples/06_skill_injection/`

**演示**：Skill 注入 Agent — Agent 在执行时可以获取 Skill 内容。

**场景设计**：
- Skill "writing_guidelines"：source 是一段写作指南文本，inject_to 指向 Agent "writer"
- Agent "writer"：接收 input + 被注入的 skill 文本，输出结果
- 展示 SkillAdapter 如何加载 skill 并传递给 AgentAdapter

**run.py 要求**：
- 声明 SkillSpec（source="inline:..."，inject_to=[CapabilityRef(id="writer")]）
- 声明 AgentSpec（skills=[CapabilityRef(id="writing_guidelines")]）
- mock AgentAdapter 的 runner 接收 skills_text 参数并在输出中体现
- 展示 Skill 注入的数据流
- 总长度 80-120 行

**注意**：如果当前 SkillAdapter 的 inject_to 机制在 v0.4.0 中尚未完整实现，
run.py 中可以在注释中说明"inject_to 将在后续版本实现"，
但仍然展示声明方式和预期行为。

---

## 产出 4：`examples/07_skill_dispatch/`

**演示**：Skill 的 dispatch_rules 触发 Agent 执行。

**场景设计**：
- Skill "router_skill"：dispatch_rules 包含规则"当 trigger='analyze' 时调度 Agent analyzer"
- Agent "analyzer"：执行分析任务
- 展示 Skill 不只是被动文档，还能主动调度其他能力

**run.py 要求**：
- 声明 SkillSpec（dispatch_rules=[SkillDispatchRule(trigger="analyze", target=CapabilityRef(id="analyzer"))]）
- 通过 SkillAdapter + Runtime 展示调度链路
- mock 化执行
- 总长度 60-100 行

**注意**：同上，如果 dispatch_rules 在当前版本中是协议层声明但 adapter 尚未完整实现，
在注释中说明即可，重点是展示声明方式。

---

## 产出 5：`examples/08_nested_workflow/`

**演示**：Workflow 嵌套 Workflow + 递归深度保护。

**场景设计**（改编自种子代码 C，但更有实际意义）：
- WF-inner "data_pipeline"：2 个 Agent 顺序执行（收集→清洗）
- WF-outer "full_pipeline"：先调用 Agent "config_loader"，然后调用 WF-inner，最后调用 Agent "report_generator"
- 展示 Workflow step 的 capability 可以引用另一个 Workflow
- 同时演示 max_depth 保护：构建一个 4 层嵌套，配置 max_depth=3，展示失败

**run.py 要求**：
- 两个场景在同一个文件中，通过函数分隔
- `async def demo_nested_success()` — 正常 2 层嵌套
- `async def demo_nested_depth_limit()` — 4 层嵌套触发深度限制
- 总长度 100-140 行

---

## 交付清单

```
docs_for_coding_agent/
├── 00-mental-model.md                 ✅
└── 01-capability-inventory.md         ✅

examples/
├── 06_skill_injection/
│   ├── README.md                      ✅
│   └── run.py                         ✅
├── 07_skill_dispatch/
│   ├── README.md                      ✅
│   └── run.py                         ✅
└── 08_nested_workflow/
    ├── README.md                      ✅
    └── run.py                         ✅
```

**验证**：
```bash
python examples/06_skill_injection/run.py
python examples/07_skill_dispatch/run.py
python examples/08_nested_workflow/run.py
python -m pytest tests/ -v
```
