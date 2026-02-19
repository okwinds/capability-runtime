# agently-skills-runtime — 编码智能体上下文提示包

> **用途**：本文档是给编码智能体（Codex CLI / Claude Code / 其他）的"全局上下文"。
> 在执行任何 BATCH 指令之前，编码智能体必须先读完本文档，建立对框架的完整理解。
>
> **使用方式**：将本文件放入仓库根目录或 `instructcontext/` 中，在 AGENTS.md 或
> SKILLS.md 中引用，告诉编码智能体："执行任务前，先读 `CODEX_CONTEXT_BRIEF.md`"。

---

## 0. 框架一句话定位

**agently-skills-runtime** 是一个**面向能力（Capability-Oriented）**的 AI 代理编排框架。
它提供三种对等的元能力原语——**Skill**（知识性能力）、**Agent**（智能性能力）、
**Workflow**（结构性能力）——它们可以**互相嵌套、自由组合**。
框架桥接上游 Agently（LLM 传输 + 编排）和 skills-runtime-sdk（Agent 引擎 + 工具），
但自身**零侵入上游、零侵入业务**。

---

## 1. 架构总览

```
┌─────────────────────────────────────────────────┐
│ 业务层（Agent Domain）— 用户实现                     │
│                                                   │
│ · 定义各原子 Agent 的 AgentSpec                      │
│ · 定义各 Workflow 的 WorkflowSpec                    │
│ · 定义 Skills（知识模板）                             │
│ · 实现存储、人机交互、服务层                            │
│                                                   │
├─────────────────────────────────────────────────┤
│ 框架层（agently-skills-runtime）                     │
│                                                   │
│ Protocol：CapabilitySpec/AgentSpec/WorkflowSpec 等  │
│ Runtime ：Registry + Engine + Guards + LoopCtrl    │
│ Adapters：AgentAdapter / WorkflowAdapter / SkillA. │
│ Bridge  ：Agently LLM → SDK ChatBackend            │
│ Reporting：执行报告聚合                              │
│                                                   │
├─────────────────────────────────────────────────┤
│ 上游层                                             │
│                                                   │
│ Agently 4.0.7：LLM requester + TriggerFlow +       │
│   Prompt 管理 + 结构化输出                           │
│                                                   │
│ skills-runtime-sdk 0.1.1：Agent 引擎 + Tools +      │
│   Skills 管理 + Sandbox                             │
└─────────────────────────────────────────────────┘
```

**依赖方向**：业务层 → 框架层 → 上游层（**严格单向**，不可反转）

---

## 2. 六条设计原则（代码中必须遵守）

| # | 原则 | 含义 |
|---|------|------|
| 1 | 上游零侵入 | 不 fork、不 patch Agently/SDK |
| 2 | 执行委托上游 | 框架只组织（声明+注册+校验+调度），不自己跑 LLM |
| 3 | 协议层独立 | protocol/ 全部是 dataclass/Enum，零上游 import |
| 4 | 业务无关 | 框架内不出现任何业务词汇（"漫剧""选题""分镜"等） |
| 5 | 可审计可恢复 | 每次执行返回 CapabilityResult + ExecutionContext 可追溯 |
| 6 | 渐进采用 | 可以只用 bridge，也可以用完整 Protocol+Runtime+Adapters |

---

## 3. 核心 API 速查

### 3.1 Protocol 层（纯类型声明，零依赖）

```python
from agently_skills_runtime.protocol.capability import (
    CapabilitySpec,    # 基础能力描述 (id, kind, name, description, tags, metadata)
    CapabilityKind,    # 枚举: SKILL | AGENT | WORKFLOW
    CapabilityRef,     # 引用: (id, kind?)
    CapabilityResult,  # 执行结果: (status, output, error, metadata, duration_ms, report)
    CapabilityStatus,  # 枚举: SUCCESS | FAILED | SKIPPED
)

from agently_skills_runtime.protocol.skill import (
    SkillSpec,         # (base, source, source_type, dispatch_rules, inject_to)
    SkillDispatchRule,  # (trigger, target)
)

from agently_skills_runtime.protocol.agent import (
    AgentSpec,         # (base, skills, tools, prompt_template, system_prompt,
                       #  output_schema, loop_compatible, io_schema)
    AgentIOSchema,     # (input_schema, output_schema)
)

from agently_skills_runtime.protocol.workflow import (
    WorkflowSpec,       # (base, steps, context_schema, output_mappings)
    Step,               # (id, capability, input_mappings)
    LoopStep,           # (id, capability, iterate_over, item_input_mappings,
                        #  max_iterations, collect_as)
    ParallelStep,       # (id, branches, join_strategy)
    ConditionalStep,    # (id, condition_source, branches, default)
    InputMapping,       # (source, target_field)
)

from agently_skills_runtime.protocol.context import (
    ExecutionContext,   # (run_id, bag, step_outputs, call_chain, depth, max_depth)
    RecursionLimitError,
)
```

### 3.2 Runtime 层（引擎 + 注册 + 护栏）

```python
from agently_skills_runtime.runtime.engine import (
    CapabilityRuntime,  # 主入口
    RuntimeConfig,      # (max_depth=10, max_total_loop_iterations=50000,
                        #  default_loop_max_iterations=200)
    AdapterProtocol,    # Protocol: async execute(*, spec, input, context, runtime)
)
```

**CapabilityRuntime 公共 API**：

```python
rt = CapabilityRuntime(config=RuntimeConfig(max_depth=10))

# 1. 注入适配器
rt.set_adapter(CapabilityKind.AGENT, my_agent_adapter)
rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
rt.set_adapter(CapabilityKind.SKILL, SkillAdapter())

# 2. 注册能力
rt.register(agent_spec)
rt.register_many([spec1, spec2, spec3])

# 3. 校验依赖（所有 CapabilityRef 引用的 id 是否已注册）
missing = rt.validate()
assert not missing, f"Missing capabilities: {missing}"

# 4. 执行
result = await rt.run(
    "capability-id",
    input={"key": "value"},
    context_bag={"shared": "data"},
)
assert result.status == CapabilityStatus.SUCCESS
print(result.output)
```

### 3.3 Adapters 层（桥接上游执行引擎）

```python
from agently_skills_runtime.adapters.agent_adapter import AgentAdapter
from agently_skills_runtime.adapters.workflow_adapter import WorkflowAdapter
from agently_skills_runtime.adapters.skill_adapter import SkillAdapter
```

**AgentAdapter**：接受一个 `runner` callable，实际执行委托给上游。

```python
# runner 签名：
async def runner(*, spec: AgentSpec, input: dict, skills_text: str,
                 context: ExecutionContext, runtime: CapabilityRuntime) -> CapabilityResult
```

**WorkflowAdapter**：内置，根据 WorkflowSpec.steps 自动编排。

**SkillAdapter**：加载 SkillSpec 内容，处理 dispatch_rules。

### 3.4 InputMapping 的 6 种 source 前缀

| 前缀 | 语义 | 示例 |
|------|------|------|
| `context.{key}` | 从 context bag 读取 | `"context.story_synopsis"` |
| `previous.{key}` | 从上一步输出读取 | `"previous.character_list"` |
| `step.{step_id}.{key}` | 从指定步骤的输出读取字段 | `"step.plan.character_list"` |
| `step.{step_id}` | 步骤输出整体 | `"step.design"` |
| `literal.{value}` | 字面量字符串 | `"literal.default_style"` |
| `item` / `item.{key}` | 循环中当前迭代元素 | `"item.role_name"` |

---

## 4. 三元对等 + 互嵌组合（核心卖点）

### 4.1 什么是"三元对等"

Skill、Agent、Workflow 不是继承关系，不是容器/被容器关系。
它们是**对等的能力原语**，共享同一个基类 `CapabilitySpec`，通过同一个
`CapabilityRuntime` 注册和执行，通过同一个 `CapabilityRef` 引用。

### 4.2 互嵌关系

```
┌──────────┐
│ Skill    │──── dispatch_rules ────→ 可调度 Agent 或 Workflow
│          │──── inject_to ─────────→ 可注入 Agent
└──────────┘

┌──────────┐
│ Agent    │──── skills 列表 ────────→ 可装载 Skill
│          │
└──────────┘

┌──────────┐
│ Workflow  │──── steps[].capability → 可编排 Agent、Skill 或另一个 Workflow
│          │
└──────────┘
```

所有互嵌通过 `runtime._execute()` 递归实现，受 `ExecutionContext.max_depth` 保护。

### 4.3 6 种典型组合模式

| # | 模式名 | 描述 | 代码要点 |
|---|--------|------|---------|
| 1 | **Agent 独立执行** | 最简单的模式 | `rt.run("agent-id", input={...})` |
| 2 | **Workflow 顺序编排** | N 个 Agent 顺序执行 | `WorkflowSpec(steps=[Step(...), Step(...)])` |
| 3 | **Workflow 循环编排** | 对列表中每个元素调用 Agent | `LoopStep(iterate_over="step.X.list", ...)` |
| 4 | **Workflow 并行编排** | 多个 Agent 并行执行 | `ParallelStep(branches=[...])` |
| 5 | **Workflow 条件分支** | 根据上一步输出走不同分支 | `ConditionalStep(condition_source="...", branches={...})` |
| 6 | **Workflow 嵌套 Workflow** | Workflow A 的 step 调用 Workflow B | `Step(capability=CapabilityRef(id="WF-B"))` |

---

## 5. 安全护栏

| 护栏 | 位置 | 默认值 | 作用 |
|------|------|--------|------|
| 递归深度 | `ExecutionContext.max_depth` | 10 | 防止无限嵌套 |
| 单步循环上限 | `LoopStep.max_iterations` | 100 | 防止单个循环失控 |
| 全局循环上限 | `ExecutionGuards.max_total_loop_iterations` | 50000 | 全局熔断器 |
| 循环失败策略 | `LoopController.fail_strategy` | `"abort"` | 单步失败后行为：abort/skip/collect |

---

## 6. 目录结构（v0.4.0 当前）

```
agently-skills-runtime/
├── src/agently_skills_runtime/
│   ├── __init__.py
│   ├── bridge.py            # AgentlySkillsRuntime（Agently→SDK 桥接）
│   ├── config.py            # 配置
│   ├── types.py             # 公共类型
│   ├── errors.py            # 异常
│   │
│   ├── protocol/            # 层 1：纯类型声明
│   │   ├── capability.py    # CapabilitySpec, Kind, Ref, Result, Status
│   │   ├── skill.py         # SkillSpec, SkillDispatchRule
│   │   ├── agent.py         # AgentSpec, AgentIOSchema
│   │   ├── workflow.py      # WorkflowSpec, Step, LoopStep, ...
│   │   └── context.py       # ExecutionContext, RecursionLimitError
│   │
│   ├── runtime/             # 层 2：引擎 + 护栏
│   │   ├── engine.py        # CapabilityRuntime, RuntimeConfig, AdapterProtocol
│   │   ├── registry.py      # CapabilityRegistry
│   │   ├── guards.py        # ExecutionGuards, LoopBreakerError
│   │   └── loop.py          # LoopController
│   │
│   ├── adapters/            # 层 3：上游适配
│   │   ├── agent_adapter.py
│   │   ├── workflow_adapter.py
│   │   ├── skill_adapter.py
│   │   ├── agently_backend.py   # 保留：AgentlyChatBackend
│   │   └── triggerflow_tool.py  # 保留：TriggerFlowTool
│   │
│   └── reporting/
│       └── node_report.py   # NodeReportV2 / NodeResultV2
│
├── tests/
│   ├── protocol/            # 15+ 单测
│   ├── runtime/             # 27+ 单测
│   ├── adapters/            # 21+ 单测
│   └── scenarios/           # 3+ 场景测试
│       ├── test_wf001d_character_creation.py
│       └── test_nested_workflow.py
│
└── pyproject.toml           # version = "0.4.0"
```

---

## 7. 种子代码（编码智能体必读的参考实现）

以下代码是已通过测试的真实代码，编码智能体在生成示例/文档时应以此为"地面真相"。

### 7.1 种子代码 A：最小 Agent 执行

```python
"""最小 AgentSpec 声明 + mock 执行。"""
from __future__ import annotations
import asyncio
from agently_skills_runtime.protocol.capability import (
    CapabilityKind, CapabilityRef, CapabilityResult, CapabilitySpec, CapabilityStatus,
)
from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.runtime.engine import CapabilityRuntime, RuntimeConfig

class MockAgentAdapter:
    """最简单的 mock adapter：直接返回固定结果。"""
    async def execute(self, *, spec, input, context, runtime):
        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output={"reply": f"Hello from {spec.base.name}!", "received": input},
        )

async def main():
    # 1. 声明
    agent = AgentSpec(
        base=CapabilitySpec(
            id="greeter",
            kind=CapabilityKind.AGENT,
            name="Greeter Agent",
            description="A simple greeting agent",
        ),
    )

    # 2. 组装 Runtime
    rt = CapabilityRuntime(config=RuntimeConfig())
    rt.set_adapter(CapabilityKind.AGENT, MockAgentAdapter())
    rt.register(agent)
    assert not rt.validate()

    # 3. 执行
    result = await rt.run("greeter", input={"user_name": "Alice"})
    assert result.status == CapabilityStatus.SUCCESS
    print(result.output)  # {"reply": "Hello from Greeter Agent!", "received": {"user_name": "Alice"}}

asyncio.run(main())
```

### 7.2 种子代码 B：WF-001D 完整场景（已通过的测试）

```python
"""场景测试：WF-001D 人物塑造子流程。
MA-013A → [MA-013×3] → MA-014 → [MA-015×3]
"""
from __future__ import annotations
import pytest
from agently_skills_runtime.adapters.workflow_adapter import WorkflowAdapter
from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.protocol.capability import (
    CapabilityKind, CapabilityRef, CapabilityResult, CapabilitySpec, CapabilityStatus,
)
from agently_skills_runtime.protocol.workflow import (
    InputMapping, LoopStep, Step, WorkflowSpec,
)
from agently_skills_runtime.runtime.engine import CapabilityRuntime, RuntimeConfig


class MockAgentAdapter:
    """按 Agent ID 返回不同结果的 mock。"""
    async def execute(self, *, spec, input, context, runtime):
        agent_id = spec.base.id

        if agent_id == "MA-013A":
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={
                    "角色列表": [
                        {"定位": "女主-天真少女", "重要性": "核心"},
                        {"定位": "男主-冷面总裁", "重要性": "核心"},
                        {"定位": "反派-心机女", "重要性": "重要"},
                    ],
                },
            )

        if agent_id == "MA-013":
            role = input.get("角色定位", "未知")
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"角色小传": f"{role}的完整人物设定...", "外貌": "...", "性格": "..."},
            )

        if agent_id == "MA-014":
            chars = input.get("角色小传列表", [])
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"关系图谱": f"共{len(chars)}个角色的关系...", "核心冲突": "三角关系"},
            )

        if agent_id == "MA-015":
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"视觉关键词": ["长发", "白裙", "月光下"], "风格": "日系"},
            )

        return CapabilityResult(status=CapabilityStatus.FAILED, error=f"Unknown: {agent_id}")


@pytest.mark.asyncio
async def test_wf001d_full_flow():
    # 声明 Agents
    agents = [
        AgentSpec(base=CapabilitySpec(id="MA-013A", kind=CapabilityKind.AGENT, name="角色定位规划师")),
        AgentSpec(base=CapabilitySpec(id="MA-013", kind=CapabilityKind.AGENT, name="单角色设计师"), loop_compatible=True),
        AgentSpec(base=CapabilitySpec(id="MA-014", kind=CapabilityKind.AGENT, name="角色关系架构师")),
        AgentSpec(base=CapabilitySpec(id="MA-015", kind=CapabilityKind.AGENT, name="角色视觉化师"), loop_compatible=True),
    ]

    # 声明 Workflow
    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-001D", kind=CapabilityKind.WORKFLOW, name="人物塑造子流程"),
        steps=[
            Step(
                id="plan",
                capability=CapabilityRef(id="MA-013A"),
                input_mappings=[InputMapping(source="context.故事梗概", target_field="故事梗概")],
            ),
            LoopStep(
                id="design",
                capability=CapabilityRef(id="MA-013"),
                iterate_over="step.plan.角色列表",
                item_input_mappings=[
                    InputMapping(source="item.定位", target_field="角色定位"),
                    InputMapping(source="context.故事梗概", target_field="故事梗概"),
                ],
                max_iterations=20,
            ),
            Step(
                id="relations",
                capability=CapabilityRef(id="MA-014"),
                input_mappings=[InputMapping(source="step.design", target_field="角色小传列表")],
            ),
            LoopStep(
                id="visual",
                capability=CapabilityRef(id="MA-015"),
                iterate_over="step.design",
                item_input_mappings=[InputMapping(source="item", target_field="角色小传")],
                max_iterations=20,
            ),
        ],
        output_mappings=[
            InputMapping(source="step.design", target_field="角色小传列表"),
            InputMapping(source="step.relations", target_field="角色关系图谱"),
            InputMapping(source="step.visual", target_field="视觉关键词列表"),
        ],
    )

    # 组装 + 执行
    rt = CapabilityRuntime(config=RuntimeConfig(max_depth=10))
    rt.set_adapter(CapabilityKind.AGENT, MockAgentAdapter())
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    for a in agents:
        rt.register(a)
    rt.register(wf)
    assert not rt.validate()

    result = await rt.run("WF-001D", context_bag={"故事梗概": "霸道总裁爱上灰姑娘的故事"})
    assert result.status == CapabilityStatus.SUCCESS
    assert len(result.output["角色小传列表"]) == 3
    assert "角色关系图谱" in result.output
    assert len(result.output["视觉关键词列表"]) == 3
```

### 7.3 种子代码 C：Workflow 嵌套 Workflow

```python
"""场景测试：Workflow 嵌套 Workflow + 递归深度保护。"""
from __future__ import annotations
import pytest
from agently_skills_runtime.adapters.workflow_adapter import WorkflowAdapter
from agently_skills_runtime.protocol.capability import (
    CapabilityKind, CapabilityRef, CapabilityResult, CapabilitySpec, CapabilityStatus,
)
from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.protocol.workflow import Step, WorkflowSpec
from agently_skills_runtime.runtime.engine import CapabilityRuntime, RuntimeConfig


class SimpleAdapter:
    async def execute(self, *, spec, input, context, runtime):
        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output={"from": spec.base.id, "depth": context.depth},
        )


@pytest.mark.asyncio
async def test_workflow_calls_workflow():
    """WF-outer → WF-inner → Agent A"""
    inner = WorkflowSpec(
        base=CapabilitySpec(id="WF-inner", kind=CapabilityKind.WORKFLOW, name="inner"),
        steps=[Step(id="s1", capability=CapabilityRef(id="A"))],
    )
    outer = WorkflowSpec(
        base=CapabilitySpec(id="WF-outer", kind=CapabilityKind.WORKFLOW, name="outer"),
        steps=[Step(id="s1", capability=CapabilityRef(id="WF-inner"))],
    )
    agent = AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"))

    rt = CapabilityRuntime(config=RuntimeConfig(max_depth=10))
    rt.set_adapter(CapabilityKind.AGENT, SimpleAdapter())
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    rt.register_many([agent, inner, outer])

    result = await rt.run("WF-outer")
    assert result.status == CapabilityStatus.SUCCESS


@pytest.mark.asyncio
async def test_deep_nesting_hits_limit():
    """超过 max_depth 时自动失败。"""
    specs = []
    for i in range(5):
        next_id = f"WF-{i+1}" if i < 4 else "A"
        specs.append(WorkflowSpec(
            base=CapabilitySpec(id=f"WF-{i}", kind=CapabilityKind.WORKFLOW, name=f"wf-{i}"),
            steps=[Step(id="s1", capability=CapabilityRef(id=next_id))],
        ))
    specs.append(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A")))

    rt = CapabilityRuntime(config=RuntimeConfig(max_depth=3))
    rt.set_adapter(CapabilityKind.AGENT, SimpleAdapter())
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    rt.register_many(specs)

    result = await rt.run("WF-0")
    assert result.status == CapabilityStatus.FAILED
    assert "depth" in (result.error or "").lower() or "recursion" in (result.error or "").lower()
```

---

## 8. 编码智能体的写作规范

### 8.1 代码风格

- 文件开头始终包含 `from __future__ import annotations`
- 所有类型注解完整（参数、返回值）
- 每个文件开头有 docstring 说明"这个文件演示什么"
- import 顺序：标准库 → 第三方 → 本框架
- 变量名和输出内容使用英文（不使用业务中文词汇，除非明确展示业务场景）

### 8.2 示例风格

- 每个示例目录包含 `README.md`（说明、前置条件、运行方法）和 `run.py`（可运行代码）
- 默认离线可运行：使用 mock adapter，不依赖真实 LLM
- 如果需要真实 LLM，标记 `# Requires: OPENAI_API_KEY` 并提供 `.env.example`
- 每个示例可独立运行：`python examples/01_xxx/run.py`

### 8.3 文档风格

- docs_for_coding_agent/ 下的文档面向**编码智能体**，语言精练、代码优先、少叙述
- 代码片段必须**可复制粘贴直接运行**
- 避免长段落解释；用代码注释代替

### 8.4 绝对禁止

- ❌ 在示例中直接 import Agently 或 SDK（应通过框架的 Adapter）
- ❌ 在 Workflow 内部手动调用 LLM（应通过 `runtime._execute` 递归）
- ❌ 忘记 `rt.validate()`（注册后必须校验依赖）
- ❌ 在 protocol/ 层 import 上游包
- ❌ 在框架代码中使用业务词汇

---

## 9. 离线验证门禁

所有生成的代码必须通过以下验证：

```bash
# 安装（开发模式）
pip install -e ".[dev]"

# 运行全量测试
python -m pytest tests/ -v

# 运行单个示例
python examples/01_xxx/run.py
```

---

## 10. 与 Agently docs_for_coding_agent 的差异

| 维度 | Agently 教学包 | 本框架教学包 |
|------|---------------|-------------|
| 教什么 | 怎么调 LLM、怎么用 TriggerFlow | 怎么声明能力、怎么组合能力、怎么编排能力 |
| 核心概念 | Agent + Request + TriggerFlow | Skill/Agent/Workflow 三元对等 |
| 示例模式 | 单文件 .py，逐步递进 | 单目录（README + run.py），逐步递进 |
| 是否需 LLM | 大部分需要 | 大部分不需要（mock 优先） |
| 关注点 | LLM 传输、streaming、tools | 声明式编排、循环/并行/条件、互嵌组合 |

---

## 11. Agently 上游速查（仅供"接线"场景参考）

编码智能体在做 Bridge 接线示例时，需要了解 Agently 的最小用法：

```python
from agently import Agently

# 全局 LLM 配置
Agently.set_settings("OpenAICompatible", {
    "base_url": "http://localhost:11434/v1",
    "model": "qwen2.5:7b",
})

# 创建 agent + 结构化输出
agent = Agently.create_agent()
result = (
    agent
    .input("根据梗概设计角色")
    .info("梗概", "霸道总裁爱上灰姑娘")
    .output({"角色列表": [{"定位": (str,), "重要性": (str,)}]})
    .start()
)
```

**注意**：在本框架的示例中，Agently 只在"Bridge 接线"场景使用。
框架层和 Protocol 层的示例一律使用 mock adapter。
