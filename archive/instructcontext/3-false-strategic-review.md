# `agently-skills-runtime` 战略方向与现状审视

> 审视日期: 2026-02-19
> 审视范围: 仓库 `okwinds/agently-skills-runtime` 全量代码、文档、instructcontext、上游 Agently 4.0.7 + SDK 0.1.1

---

## 一、战略意图的精确陈述

### 1.1 你的核心判断（我所理解的）

你要建的不是一个"从零开始的 AI Agent 框架"，而是一个**面向能力的组织层（Capability-oriented Orchestration Layer）**，它的存在理由是：

- **上游 Agently** 提供了完整的 LLM 传输能力（OpenAICompatible requester、streaming、structured output）和 TriggerFlow 工作流编排引擎（事件驱动、并发、状态管理）
- **上游 skills-runtime-sdk** 提供了 Agent 执行引擎（`Agent.run_stream_async()`、tool dispatch、event loop）、SkillsManager（preflight/scan）、WAL 证据链
- **本仓库** 不应重写上述能力，而应做两件事：
  1. **桥接（Bridge）**：把两个上游的互补能力黏合成一个可用的执行闭环
  2. **组织（Organize）**：在桥接之上，提供"面向能力"的声明、注册、组合、调度能力，让业务层可以声明式地编排 Skill → Agent → Workflow

用一句话说：**本仓库 = 桥接层（执行委托上游） + 能力组织层（声明/注册/组合/调度委托上游执行）**。

### 1.2 这个判断为什么正确

| 维度 | 自研一切（v0.2.0 的错） | 纯桥接无组织（v0.3.0 当前） | 桥接 + 能力组织（正确方向） |
|------|----------------------|--------------------------|--------------------------|
| 维护成本 | 极高：等于维护第三套框架 | 低：但业务层无抓手 | 中：只维护薄组织层 |
| 上游进化跟随 | 脱钩：上游升级与你无关 | 自动跟随 | 自动跟随 |
| 业务落地速度 | 慢：先造引擎再做业务 | 快但乱：业务直接调原始 API | 快且有序：声明式编排 |
| 对业务的价值 | 低：mock 能跑但连不上真 LLM | 有但有限：单 Agent 调用 | 高：多 Agent + Workflow 编排 |

### 1.3 与业务域的边界

```
┌─────────────────────────────────────────────────────┐
│ 业务域（AI 漫剧生产）                                   │
│ ┌─────────────────────────────────────────────────┐ │
│ │ 业务定义：                                         │ │
│ │ · TP0~TP6 各环节的 Agent 声明（MA-001~MA-027）       │ │
│ │ · WF-001~WF-004 各 Workflow 定义                   │ │
│ │ · 循环调用机制（角色循环、章节循环、分镜循环）             │ │
│ │ · 存储架构（制品归档、WAL、状态持久化）                  │ │
│ └─────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────┤
│ 框架层（agently-skills-runtime）                        │
│ ┌───────────────┐  ┌─────────────────────────────┐ │
│ │ 能力组织层       │  │ 桥接层                        │ │
│ │ · Protocol      │  │ · AgentlyChatBackend        │ │
│ │ · Registry      │  │ · TriggerFlowTool           │ │
│ │ · Engine        │  │ · AgentlySkillsRuntime      │ │
│ │ · Guards        │  │ · NodeReportBuilder         │ │
│ └───────┬───────┘  └──────────┬──────────────────┘ │
│         │  dispatch via       │  execution via      │
├─────────┴──────────────────────┴────────────────────┤
│ 上游                                                  │
│ · Agently (LLM transport + TriggerFlow)               │
│ · skills-runtime-sdk (Agent engine + Skills + WAL)    │
└─────────────────────────────────────────────────────┘
```

---

## 二、v0.3.0 当前状态的如实审视

### 2.1 已完成的（✅ 正确且可用）

| 模块 | 状态 | 说明 |
|------|------|------|
| `AgentlyChatBackend` | ✅ 恢复 | Agently requester → SDK ChatBackend，LLM 传输桥接正确 |
| `AgentlySkillsRuntime` | ✅ 恢复 | 构造 SDK Agent、注入 backend、preflight gate、运行并聚合事件 |
| `TriggerFlowTool` | ✅ 恢复 | 以 tool 触发 TriggerFlow，含 approvals 证据链 |
| `NodeReportBuilder` | ✅ 恢复 | 从 SDK AgentEvent 聚合强结构化报告 |
| `NodeReportV2/NodeResultV2` | ✅ 恢复 | 控制面强结构类型 |
| `config.py` (BridgeConfigModel) | ✅ 可用 | Pydantic 配置模型 |
| 上游 fork 校验 | ✅ 可用 | upstream verification (off/warn/strict) |
| 离线回归 | ✅ 通过 | `pytest -q` 通过（含 1 条 integration skip） |
| v0.2.0 归档 | ✅ 完整 | `legacy/2026-02-19-v0.2.0-self-contained/` |

### 2.2 缺失的（❌ 尚未开始）

| 能力 | 缺失说明 | 对业务的影响 |
|------|---------|------------|
| **Protocol 层** | 无 CapabilitySpec/SkillSpec/AgentSpec/WorkflowSpec 声明 | 业务无法声明式定义 MA-001~027 和 WF-001~004 |
| **CapabilityRegistry** | 无能力注册表 | 无法按 ID 查找/发现/校验依赖 |
| **CapabilityRuntime（组织层主入口）** | 无统一的 register → validate → run 入口 | 业务只能直接调 `AgentlySkillsRuntime.run_async()`，无法编排 |
| **ExecutionContext** | 无调用链追踪、递归深度控制、状态传递 | 嵌套调用无保护，状态不可追踪 |
| **LoopController + ExecutionGuards** | 无循环/递归熔断 | 业务的 8 种循环场景（MA-006/013/015/021/024/025/026/027）无安全护栏 |
| **Adapters（组织层）** | 无 SkillAdapter/AgentAdapter/WorkflowAdapter | 组织层无法分发到桥接层执行 |
| **Workflow 编排** | 无 Step/LoopStep/ParallelStep/ConditionalStep | 无法表达 WF-001 的"WF-001A → WF-001B → ... → WF-001G"编排 |

### 2.3 诚实判断

**v0.3.0 做对了方向（回归桥接），但只完成了"下半身"（执行引擎）。"上半身"（能力组织层）完全缺失。**

当前能做的事：用 `AgentlySkillsRuntime.run_async("请帮我写一个故事大纲")` 跑单次 Agent 调用。

不能做的事：声明 MA-001~027 的能力规格，注册到 Registry，用 WF-001 编排它们，安全地循环调用 MA-021 扩写 30 章。

---

## 三、正确的架构方向（桥接 + 能力组织层）

### 3.1 关键原则

1. **Protocol 层不依赖上游** — 纯 dataclass/Enum，任何人看了就知道"能力长什么样"
2. **Runtime 层不依赖上游** — Registry/Guards/Engine 只做分发和保护，不执行真实 LLM
3. **Adapters 层桥接上游** — 这是唯一 import 上游的地方，且只用 Public API
4. **桥接层保持不变** — v0.3.0 已有的 `AgentlySkillsRuntime` / `AgentlyChatBackend` / `TriggerFlowTool` 继续作为底层执行引擎
5. **业务层在框架之上** — 框架不知道 MA-001 是什么，业务层声明并注册

### 3.2 目标包结构

```
src/agently_skills_runtime/
├── __init__.py                         # 公共 API 导出
│
├── protocol/                           # 能力协议（纯类型，不依赖上游）
│   ├── capability.py                   # CapabilitySpec/Kind/Ref/Result/Status
│   ├── skill.py                        # SkillSpec, SkillDispatchRule
│   ├── agent.py                        # AgentSpec, AgentIOSchema
│   ├── workflow.py                     # WorkflowSpec, Step/Loop/Parallel/Conditional
│   └── context.py                      # ExecutionContext, RecursionLimitError
│
├── runtime/                            # 能力运行时（不依赖上游）
│   ├── engine.py                       # CapabilityRuntime（register/validate/run 分发）
│   ├── registry.py                     # CapabilityRegistry（注册/查找/依赖校验）
│   ├── loop.py                         # LoopController（循环控制）
│   └── guards.py                       # ExecutionGuards + LoopBreakerError
│
├── adapters/                           # 上游桥接适配器
│   ├── agently_backend.py              # AgentlyChatBackend（已有 ✅）
│   ├── triggerflow_tool.py             # TriggerFlowTool（已有 ✅）
│   ├── skill_adapter.py               # SkillAdapter → SDK SkillsManager
│   ├── agent_adapter.py               # AgentAdapter → AgentlySkillsRuntime
│   └── workflow_adapter.py             # WorkflowAdapter → TriggerFlow
│
├── bridge/                             # 桥接层主入口（已有 ✅，从当前 runtime.py 迁入）
│   └── runtime.py                      # AgentlySkillsRuntime（原有代码）
│
├── reporting/                          # 执行报告（已有 ✅）
│   └── node_report.py
│
├── config.py                           # 配置（已有 ✅）
├── errors.py                           # 框架错误
└── types.py                            # NodeReportV2/NodeResultV2（已有 ✅）
```

### 3.3 各 Adapter 与上游的关系（关键区别）

**v0.2.0 的错误**：Adapters 自己实现执行逻辑。
**v0.3.1 的正确做法**：Adapters 调用上游的真实 API。

| Adapter | 做什么 | 调用上游什么 |
|---------|--------|------------|
| `SkillAdapter` | 从 SkillSpec 加载内容，注入到 Agent context | SDK `SkillsManager.scan()` 获取 skills，注入到 Agent 的 prompt |
| `AgentAdapter` | 从 AgentSpec 构造并执行 Agent | 调用 `AgentlySkillsRuntime.run_async()` 或直接构造 SDK Agent |
| `WorkflowAdapter` | 从 WorkflowSpec 执行步骤编排 | 用 TriggerFlow 构造 flow 并执行，或逐步调用 `CapabilityRuntime.run()` |

### 3.4 执行流示例

业务声明了 WF-001D（人物塑造子流程）:

```
WF-001D:
  steps:
    1. MA-013A (角色定位规划师) → 输出角色列表
    2. [MA-013 × N] (单角色设计师) → 循环每个角色
    3. MA-014 (角色关系架构师) → 汇总
    4. [MA-015 × N] (角色视觉化师) → 循环每个角色
```

框架执行路径：

```
业务: runtime.run("WF-001D", context_bag={"故事梗概": "..."})
  → CapabilityRuntime.run() 查 Registry 找到 WorkflowSpec
  → dispatch 到 WorkflowAdapter.execute()
    → Step 1: runtime._execute("MA-013A", ...) → AgentAdapter → AgentlySkillsRuntime → SDK Agent → LLM
    → LoopStep 2: LoopController 遍历角色列表
      → 每次: runtime._execute("MA-013", input=角色定位) → AgentAdapter → ... → LLM
      → ExecutionGuards 检查迭代次数 ≤ max_iterations
    → Step 3: runtime._execute("MA-014", ...) → AgentAdapter → ... → LLM
    → LoopStep 4: 同上
  → 返回 CapabilityResult(status=success, output=人物塑造完整包)
```

---

## 四、下一步行动计划

### 4.1 Phase 1（当前迭代）: Protocol + Runtime 骨架

**目标**：让业务可以声明能力、注册到 Registry、通过 Engine 调度到桥接层执行。

**范围**：
1. 建立 `protocol/` 5 个文件（纯 dataclass，不依赖上游）
2. 建立 `runtime/` 4 个文件（Registry/Guards/Loop/Engine，不依赖上游）
3. 建立 `adapters/agent_adapter.py`（调用已有的 `AgentlySkillsRuntime` 执行 Agent）
4. 更新 `__init__.py` 导出
5. 单测全覆盖（protocol + runtime + adapter mock）
6. **不动** 已有的桥接层代码（`runtime.py`, `agently_backend.py`, `triggerflow_tool.py`, `types.py`）

**验收标准**：
- `pip install -e .` 成功
- `pytest -q` 全部通过
- 可以声明一个 AgentSpec，注册，调用 `runtime.run("agent-id")` 跑通

### 4.2 Phase 2: WorkflowAdapter + 循环场景

**目标**：让业务可以编排多步 Workflow。

**范围**：
1. `adapters/workflow_adapter.py`（Step 顺序执行、LoopStep 循环、ParallelStep 并行）
2. `adapters/skill_adapter.py`（从 SkillSpec 加载内容，注入到 Agent）
3. Scenario 测试：模拟 WF-001D（人物塑造子流程）

### 4.3 Phase 3: TriggerFlow 顶层编排集成

**目标**：用 TriggerFlow 作为顶层编排器，编排多个 `CapabilityRuntime.run()` 调用。

---

## 五、风险提示

1. **不要再偏航到自研引擎** — 所有真实执行（LLM 调用、tool dispatch、streaming）必须委托上游
2. **Protocol 可以参考 v0.2.0 归档** — v0.2.0 的 protocol 定义是好的，可以直接复用，但 runtime/adapters 必须重写为桥接模式
3. **WorkflowAdapter 有两条路径** — A: 自己实现 step 调度（简单直接）；B: 委托 TriggerFlow（更强大但更复杂）。建议 Phase 2 先走 A，Phase 3 再走 B
4. **上游依赖是特性不是缺陷** — 离线回归需要本地 editable 安装上游，这是"胶水层"定位的自然结果
