# 面向能力范式：为什么不是 Agent Framework

> 面向：编码智能体 / 维护者  
> 目标：用“对比法”把本仓的能力范式讲清楚，避免把系统误读成“又一个 Agent Framework / 提示词工程项目”。  
> 真相源：全局口径以 `archive/instructcontext/5-true-CODEX_CONTEXT_BRIEF.md` 为准；代码层“地面真相”以 `src/` 与 `tests/` 为准。  
> 补充总纲：`docs/internal/specs/engineering-spec/00_Overview/CAPABILITY_MODEL_OVERVIEW.md`

---

## 1) 传统思路：把问题当成“Agent Framework / Prompt 工程”

传统 LLM 项目里，大家常把主要矛盾理解成：

- 怎么写更好的 prompt、怎么选模型、怎么调参数
- 怎么把 tools/函数调用接上，让 Agent 能“自己跑起来”
- 怎么在输出文本上做对齐（用 golden output 或人工评审）

这套思路不是“错”，但它会自然导向：**资产中心在 prompt/脚本，证据中心在文本输出**。一旦进入多人协作与长期维护，会遇到两个典型问题：

- 很难把“能力”拆成稳定模块做复用与组合（容易越写越像一团脚本）
- 很难把“系统为什么这么跑”变成可审计、可回归的证据链（文本对比太脆弱）

下面开始对齐本仓的真实心智模型。

---

## 2) 本仓思路：把问题当成“Bridge-only + Capability Organization”

本仓的设计中心不是“怎么调 LLM”，而是“怎么组织与运行能力”，并且**不重造上游引擎**：

- **能力原语收敛**：本仓库对外的 Protocol 原语仅 **Agent / Workflow**（共享 `CapabilitySpec`）
- **skills 真相源**：skills 的发现/mention/sources/preflight/tools/approvals/WAL 全部以 `skills-runtime-sdk-python`（模块 `agent_sdk`）为准
- **外层编排入口**：默认使用 Agently TriggerFlow（生态入口）
- **强结构证据链优先**：以 NodeReport/WAL/tool evidence 做系统级取证与回归（而不是只比输出文本）

你在这个仓库里最应该交付的核心资产通常是：**Spec（声明）+ Adapter（落地）+ Tests（护栏）**。

---

## 3) 对比表：传统思路 vs 面向能力范式

| 视角 | 传统 LLM 项目（常见误读） | 本仓（面向能力范式） |
|---|---|---|
| 设计中心 | Prompt / 模型参数 | **Capability**（Agent / Workflow + 上游 skills 引擎） |
| 可回归证据 | 输出文本对比（脆弱） | NodeReport/WAL/tool evidence（强结构） |
| 组合方式 | “把提示词拼起来” | “把能力声明组合起来”（Workflow/TriggerFlow） |
| 抽象边界 | 业务域强绑定 | **协议独立 + 业务无关**（可迁移） |

结论：  
你写的核心资产应该是 **Spec（声明）+ Adapter（落地）+ Tests（护栏）**，而不是“更聪明的提示词”。

---

## 4) 总览图：二元原语 + 上游 skills 引擎

> 重点：skills 当然也是“能力”，但它们属于 **`agent_sdk` 引擎内部的一等公民**；本仓库不再把 skill 当成第三种 Protocol 原语（避免形成第二套 skills 体系）。

```mermaid
flowchart TD
  subgraph BR[This Repo: agently-skills-runtime]
    WF[WorkflowSpec + WorkflowAdapter]
    AG[AgentSpec + AgentAdapter]
    RT[CapabilityRuntime\n(register/validate/run)]
  end

  subgraph U1[Upstream: Agently]
    TF[TriggerFlow\n(顶层编排入口)]
  end

  subgraph U2[Upstream: agent_sdk]
    SK[Skills Engine\n(strict catalog + mention + sources)]
    WAL[WAL / AgentEvent]
  end

  TF --> RT
  RT --> WF
  RT --> AG
  AG --> SK
  SK --> WAL
```

---

## 5) 边界清晰：Protocol / Runtime / Adapters / Bridge

先记住边界（它决定你“该在哪里改代码/写测试”）：

| 层 | 入口 | 一句话职责 | 允许依赖上游？ | 你在这层最常做的事 |
|---|---|---|---|---|
| Protocol | `src/agently_skills_runtime/protocol/*` | **定义类型与契约**（dataclass/Enum） | ❌ | 新增字段、写清默认值、补齐 docstring、加单测护栏 |
| Runtime | `src/agently_skills_runtime/runtime/*` | **注册/校验/调度/护栏** | ❌ | 修 engine/registry/guards/loop 的行为与测试 |
| Adapters | `src/agently_skills_runtime/adapters/*` | **把声明变成可执行**（委托/组织） | ✅（可选） | 实现 Agent/Workflow 的执行落点，保持可回归 |
| Bridge / Reporting | `src/agently_skills_runtime/bridge.py` + `reporting/*` | **上游桥接 + 证据链聚合** | ✅（必须） | Agently streaming ↔ SDK backend；SDK events ↔ NodeReport |

记忆口诀：  
Protocol 只“说是什么”；Runtime 只“管怎么跑”；Adapter 才“真的去做”；Bridge 负责“上游映射与证据链”。

执行闭环（不是“写完 spec 就能跑”）：

| 阶段 | 你做什么 | Runtime 做什么 | 常见坑 |
|---|---|---|---|
| 声明 | 写 `*Spec`（字段齐、默认值清） | 不执行 | 只写了 spec 没注册 |
| 注册 | `runtime.register(spec)` | 存入 `CapabilityRegistry` | 重复 ID 被覆盖（last-write-wins） |
| 校验 | `missing = runtime.validate()` | 检查引用依赖是否注册 | 忘记注册子能力导致 missing |
| 执行 | `await runtime.run("id", input=...)` | 递归调度到 Adapter | 未注入 Adapter → `no_adapter` |

---

## 6) 何时用 Agent / Workflow（以及 skills 怎么办）

### 6.1 什么时候用 Agent / Workflow

- 用 **Agent**：你要交付“一次可执行的任务能力”（它会生成 task，委托 runner/bridge 执行，并产出可审计结果）。
- 用 **Workflow**：你要交付“主流程编排”（step/loop/parallel/conditional），并把每步输出显式缓存到 `context.step_outputs`（推荐做主流程）。

经验法则：  
主流程一定用 Workflow；不要在本仓“自造 skills 注入/调度系统”去表达复杂分支。

### 6.2 ExecutionContext：把“数据流”显式化（`bag` vs `step_outputs`）

| 结构 | 存什么 | 写入位置 | 读取方式（常用） |
|---|---|---|---|
| `context.bag` | 跨步骤共享的数据（浅拷贝） | Workflow 开始时合并 input；也可由 Adapter 写入 | `context.{key}` |
| `context.step_outputs` | 当前 Workflow 层的步骤输出缓存 | 每个 step 执行后写入 `step_id → output` | `step.{step_id}.{key}` / `previous.{key}` |
| `context.call_chain` | 调用链（能力 ID 列表） | 由 Runtime 在创建 child context 时追加 | 用于排障/审计 |

映射表达式是“找不到返回 None”，不是抛异常：  
因此拼写错误常表现为“静默拿到 None”，排查时先打印解析值。

### 6.3 skills 怎么接入（方案2）

**不要**在本仓里实现 `SkillSpec.inject_to` / `dispatch_rules` 一类“第二套 skills 体系”。正确做法是：

1. 用 `agent_sdk` 的 **Strict Catalog + sources** 声明技能（YAML overlays）
2. 在 task/prompt 中使用 **strict mention** 引用 skills（例如 `$[space:domain].skill_name`）
3. 用本仓 `AgentlySkillsRuntime.preflight()` / `preflight_or_raise()` 做开发机 gate
4. 用 NodeReport/WAL 的证据链做编排与审计

---

## 7) 建议的“读代码顺序”（10 分钟）

1. `src/agently_skills_runtime/__init__.py`：公共 API 导出面（看看“框架承诺什么”）  
2. `src/agently_skills_runtime/runtime/engine.py`：`run()`/`_execute()` 的调度骨架  
3. `src/agently_skills_runtime/runtime/registry.py`：依赖校验（validate_dependencies）  
4. `src/agently_skills_runtime/adapters/*_adapter.py`：Agent/Workflow 的执行落点  
5. `src/agently_skills_runtime/bridge.py`：Agently ↔ agent_sdk 的桥接闭环 + NodeReport 聚合入口

下一篇：`01-capability-inventory.md`（按 Protocol/Runtime/Adapters 列清单与默认值）。

