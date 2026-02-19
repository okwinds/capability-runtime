# BATCH 3 指令：模式手册 + Bridge 接线 + 完整场景与真实 LLM（09-10）

> **前置条件**：BATCH 1 + BATCH 2 已交付并验证通过。
>
> **目标**：从 mock 世界走向真实世界——总结模式、展示完整场景、接线真实 LLM。
> 这是从"学习框架"到"使用框架"的关键转折。
>
> **特殊说明**：example 10（bridge wiring）需要接触上游 Agently 和 SDK，
> 是本框架 Phase 4A（Bridge 接线 + 真实集成验证）的落地交付物。

---

## 产出 1：`docs_for_coding_agent/02-patterns.md`

### 要求

- 标题：**6 种典型组合模式**
- 每种模式包含：场景描述 + 完整可运行代码 + 数据流图（ASCII）
- 代码基于已交付的 examples/01-08，但更聚焦于"模式"而非"教学"
- 总长度 250-350 行

### 6 种模式

```markdown
# 6 种典型组合模式

## 模式 1：Agent 独立执行
- 场景：单次 LLM 调用任务
- 数据流：input → Agent → output
- 代码：（15-20 行，从 example 01 提炼）

## 模式 2：Pipeline（顺序编排）
- 场景：多步骤线性处理
- 数据流：input → A → B → C → output
- InputMapping 要点：context. / previous. / step.X.Y 三种
- 代码：（20-30 行，从 example 02 提炼）

## 模式 3：Fan-out / Fan-in（循环编排）
- 场景：对列表中的每个元素独立处理
- 数据流：input → A → [B × N] → output（收集为列表）
- LoopStep 要点：iterate_over / item. / collect_as
- 代码：（20-30 行，从 example 03 提炼）

## 模式 4：Scatter / Gather（并行编排）
- 场景：多个视角同时分析，汇总
- 数据流：input → [A | B | C] → D → output
- ParallelStep 要点：branches / join_strategy
- 代码：（20-30 行，从 example 04 提炼）

## 模式 5：Router（条件分支）
- 场景：分类后走不同处理链
- 数据流：input → Classifier → {positive: A, negative: B, default: C}
- ConditionalStep 要点：condition_source / branches / default
- 代码：（20-30 行，从 example 05 提炼）

## 模式 6：Hierarchical（嵌套编排）
- 场景：大流程包含子流程
- 数据流：WF-outer → [A → WF-inner → [B → C] → D]
- 要点：Workflow 的 step 可以引用另一个 Workflow
- 递归保护：max_depth
- 代码：（20-30 行，从 example 08 提炼）

## 模式组合

（1-2 段说明：以上模式可以自由组合。
例如 Pipeline 的某个步骤是 Fan-out，Fan-out 的某个分支是 Router。
实际业务中的 WF-001D 就是 Pipeline + Fan-out 的组合。）
```

---

## 产出 2：`docs_for_coding_agent/03-bridge-wiring.md`

### 要求

- 标题：**Bridge 接线指南：连接真实 LLM**
- 这是将框架的 mock 世界连接到真实 LLM 的关键文档
- 面向需要做 Phase 4A 集成的编码智能体
- 总长度 150-200 行

### 结构模板

```markdown
# Bridge 接线指南

## 架构回顾

框架层 AgentAdapter 通过 runner 函数委托执行给 Bridge 层，
Bridge 层通过 Agently requester 发送 LLM 请求，
通过 SDK ChatBackend 管理工具调用。

## 接线三步法

### Step 1：配置上游 Agently
（代码：Agently.set_settings + create_agent）

### Step 2：构造 Bridge Runtime
（代码：AgentlySkillsRuntime 的构造，说明参数）

### Step 3：构造 AgentAdapter 的 runner
（代码：runner 函数签名 + 内部调用 bridge）

### Step 4：组装 CapabilityRuntime
（代码：set_adapter + register + validate + run）

## 完整接线代码
（50-70 行完整可运行代码，从 Step 1-4 串联）

## .env.example
（OPENAI_API_KEY / OPENAI_BASE_URL / MODEL_NAME）

## 注意事项
- runner 函数的签名必须与 AgentAdapter 兼容
- Skills 文本通过 skills_text 参数传递给 runner
- output_schema 通过 spec.output_schema 传递
- Bridge 层的 AgentlySkillsRuntime 已在 v0.3.0 实现，v0.4.0 保留

## 常见问题
- Q: 为什么不直接用 Agently，要绕一层框架？
  A: 框架提供声明式编排（Workflow 自动执行步骤/循环/并行），
  以及统一的类型系统（CapabilityResult 可审计）。
  直接用 Agently 需要自己写编排逻辑。
- Q: 如果只想测试单个 Agent，需要完整接线吗？
  A: 可以只用 mock adapter 测试编排逻辑，
  接线只在需要真实 LLM 输出时才需要。
```

---

## 产出 3：`examples/09_full_scenario_mock/`

**演示**：完整业务场景的 mock 版本——一个"内容创作工作流"。

**场景设计**（通用化，不用业务词汇）：
- **WF-content-creation**：一个包含顺序 + 循环 + 汇总的完整工作流
  1. Agent "topic_analyst"：输入 raw_idea → 输出 {"topic": "...", "angles": ["a1", "a2", "a3"]}
  2. LoopStep "angle_developer"：对 angles 中的每个 angle 调用 Agent "angle_writer"
     - Agent "angle_writer"：输入 angle + topic → 输出 {"section": "..."}
  3. Agent "editor"：输入 所有 sections → 输出 {"final_draft": "...", "word_count": 1200}
  4. Agent "quality_checker"：输入 final_draft → 输出 {"quality_score": 85, "issues": [...]}
- output_mappings 收集最终产出

**run.py 要求**：
- 完整展示 4 个 AgentSpec + 1 个 WorkflowSpec 的声明
- Mock adapter 根据 agent_id 返回有意义的 mock 数据（不是空字典）
- 打印完整的执行结果（包含所有 output_mappings 的输出）
- 总长度 120-180 行
- 在 README 中说明"这个场景对应了本框架的典型业务模式：Pipeline + Fan-out"

---

## 产出 4：`examples/10_bridge_wiring/`

**演示**：真实 LLM 接线——AgentAdapter 通过 Bridge 连接 Agently 的 LLM requester。

**重要**：这是本框架从 mock 走向真实的第一个示例。

**文件列表**：
```
examples/10_bridge_wiring/
├── README.md
├── run.py           # 主入口
├── .env.example     # 环境变量模板
└── wiring.py        # 接线辅助函数（可选，如果抽取有助于可读性）
```

**run.py 要求**：

```python
"""
Bridge 接线示例：通过 agently-skills-runtime 调用真实 LLM。

前置条件：
  1. pip install -e ".[dev]"
  2. pip install agently>=4.0.7
  3. cp examples/10_bridge_wiring/.env.example examples/10_bridge_wiring/.env
  4. 编辑 .env 填入真实的 API key 和 endpoint

运行方法：
  python examples/10_bridge_wiring/run.py
"""
```

**接线模式**（编码智能体参考 03-bridge-wiring.md 实现）：

1. 从 .env 读取 LLM 配置
2. 构造 Agently agent
3. 构造 Bridge runtime（AgentlySkillsRuntime）
4. 定义 runner 函数：
   ```python
   async def bridge_runner(*, spec, input, skills_text, context, runtime):
       # 用 Agently agent 发送请求
       # 将 spec.system_prompt / spec.prompt_template / input 组装为 prompt
       # 将 spec.output_schema 传给 .output()
       # 调用 .start() 获取结果
       # 包装为 CapabilityResult 返回
   ```
5. 构造 CapabilityRuntime + AgentAdapter(runner=bridge_runner)
6. 声明一个简单的 AgentSpec（例如"用一句话总结给定主题"）
7. 执行并打印结果

**总长度**：80-120 行

**降级处理**：如果 .env 不存在或 key 缺失，打印提示信息并退出（不抛异常）。

**注意**：
- 如果当前 Bridge 层（bridge.py 的 AgentlySkillsRuntime）的接口
  与上述 runner 签名不完全匹配，可以做轻量适配。
  但不修改框架代码，适配逻辑放在 wiring.py 中。
- 如果 Agently 无法在当前环境安装（例如编码智能体的沙箱环境），
  提供一个 `run_mock_fallback.py` 用 mock adapter 展示相同的声明模式，
  并在 README 中说明两种运行方式。

---

## 交付清单

```
docs_for_coding_agent/
├── 02-patterns.md                     ✅
└── 03-bridge-wiring.md                ✅

examples/
├── 09_full_scenario_mock/
│   ├── README.md                      ✅
│   └── run.py                         ✅
└── 10_bridge_wiring/
    ├── README.md                      ✅
    ├── run.py                         ✅
    ├── .env.example                   ✅
    └── run_mock_fallback.py           ✅（降级方案）
```

**验证**：
```bash
# mock 示例
python examples/09_full_scenario_mock/run.py

# 真实 LLM（需要 .env 配置）
python examples/10_bridge_wiring/run.py

# 降级
python examples/10_bridge_wiring/run_mock_fallback.py

# 回归
python -m pytest tests/ -v
```
