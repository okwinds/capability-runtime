# agently-skills-runtime 框架完整规格文档

> 版本：v0.4.0-spec-draft
> 日期：2026-02-19
> 定位：本文档是 `agently-skills-runtime` 框架的完整规格，达到 PRD + Engineering Spec 的详细度，可直接作为编码智能体的实施依据。

---

# 第一部分：战略定位与设计哲学

## 1.1 框架存在的理由

本框架解决的核心问题是：**上游 Agently 和 skills-runtime-sdk 各自提供了强大但互补的能力，需要一个"组织层 + 桥接层"把它们黏合成可编排的执行闭环。**

| 上游框架 | 提供什么 | 缺什么 |
|---------|---------|--------|
| **Agently 4.0.7** | LLM 传输（OpenAICompatible requester + streaming）、结构化输出（`output()` + `ensure_keys`）、TriggerFlow 工作流编排（事件驱动、分支、并发、循环）、Prompt 管理 | 无 tool dispatch loop、无 WAL/事件证据链、无 Skills 管理 |
| **skills-runtime-sdk 0.1.1** | Agent 执行引擎（`run_stream_async()` + tool dispatch + auto loop）、SkillsManager（preflight/scan）、WAL（JSONL 证据链）、ApprovalProvider、ToolRegistry | 无 LLM 传输实现（需注入 ChatBackend）、无 Workflow 编排器 |

**本框架的定位：**

```
本框架 = 桥接层（Bridge）+ 能力组织层（Capability Organization）

桥接层：把 Agently 的 LLM 传输能力注入 SDK 的 ChatBackend 接口，
       使 SDK Agent 可以真正调用 LLM，形成 tool dispatch 闭环。

能力组织层：在桥接之上，提供"声明→注册→校验→调度→执行→报告"的完整管线，
           使业务层可以声明式地编排 Skill → Agent → Workflow。
```

## 1.2 设计哲学（六条不可违反的原则）

### 原则一：上游零侵入
不 fork、不修改 Agently 与 skills-runtime-sdk 的源代码。只通过 Public API 适配。上游升级时，本框架自动受益。

### 原则二：执行委托上游
所有真实执行（LLM 调用、tool dispatch、streaming、WAL 写入）都由上游引擎完成。本框架只负责"组织"——决定调用谁、传什么参数、怎么处理结果。

### 原则三：协议层独立于上游
Protocol（CapabilitySpec/SkillSpec/AgentSpec/WorkflowSpec）是纯 Python dataclass/Enum，不 import 任何上游模块。任何人看协议定义就能理解"能力长什么样"。

### 原则四：不侵入业务
框架不知道"漫剧"、"选题"、"分镜"是什么。它只知道 Skill/Agent/Workflow 三种元能力，以及如何声明、注册、组合、调度它们。业务域的 MA-001~027 和 WF-001~004 由业务层定义并注册到框架。

### 原则五：可回归、可审计
每次执行都产出 CapabilityResult（含状态、输出、错误、执行报告）。嵌套调用通过 ExecutionContext 追踪完整调用链。循环和递归有硬上限保护。

### 原则六：渐进式落地
框架分层设计，业务可以只用桥接层（单 Agent 调用），也可以用完整的能力组织层（多 Agent + Workflow 编排）。不强制一步到位。

## 1.3 与业务域的边界划分

```
┌─────────────────────────────────────────────────────────┐
│ 业务域（AI 漫剧生产）                                       │
│                                                           │
│ 负责：                                                     │
│ · 定义 MA-001~MA-027 各原子 Agent 的 AgentSpec             │
│   （含 prompt 策略、输入输出 schema、skills 列表）            │
│ · 定义 WF-001~WF-004 各 Workflow 的 WorkflowSpec           │
│   （含步骤编排、循环场景、并行策略、条件分支）                   │
│ · 定义 Skills（选题评分模板、角色小传模板等）                   │
│ · 实现存储架构（制品归档、状态持久化）                          │
│ · 实现人机交互（审批、协作修改等由业务自行在步骤间编排）          │
│                                                           │
├─────────────────────────────────────────────────────────┤
│ 框架层（agently-skills-runtime）                            │
│                                                           │
│ 负责：                                                     │
│ · 提供 Protocol（CapabilitySpec/AgentSpec/WorkflowSpec 等） │
│ · 提供 Registry（能力注册、发现、依赖校验）                    │
│ · 提供 Engine（调度分发 + 递归/循环保护）                     │
│ · 提供 Adapters（桥接上游执行引擎）                           │
│ · 提供 Bridge（Agently LLM → SDK ChatBackend）              │
│ · 提供 Reporting（执行报告聚合）                              │
│                                                           │
├─────────────────────────────────────────────────────────┤
│ 上游层                                                      │
│                                                           │
│ Agently 4.0.7：                                            │
│ · OpenAICompatible requester（LLM 传输 + streaming）        │
│ · TriggerFlow（事件驱动工作流：when/if/match/for_each/batch） │
│ · Prompt 管理（Prompt.to_messages()）                       │
│ · 结构化输出（output() + ensure_keys）                       │
│                                                           │
│ skills-runtime-sdk 0.1.1：                                  │
│ · Agent 执行引擎（run/run_stream/run_stream_async）          │
│ · ToolRegistry（注册/dispatch/WAL 事件落盘）                  │
│ · SkillsManager（preflight/scan/resolve_mentions）           │
│ · ChatBackend 接口（stream_chat）                            │
│ · ApprovalProvider / HumanIOProvider                        │
│ · WAL（JSONL 证据链：events.jsonl）                          │
└─────────────────────────────────────────────────────────┘
```

---

# 第二部分：上游框架 API 深度分析

> 本节详细列举本框架需要桥接和调用的上游 API，为 Adapter 设计提供精确依据。

## 2.1 Agently 4.0.7 关键 API

### 2.1.1 LLM 传输（OpenAICompatible Requester）

```python
# 设置全局 LLM 配置
from agently import Agently

Agently.set_settings("OpenAICompatible", {
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-chat",
    "auth": "DEEPSEEK_API_KEY",
})

# 创建 Agent
agent = Agently.create_agent()

# 获取 requester（本框架桥接层使用此 API）
requester = agent.create_request().generate_request_data()
# requester 具有：
#   .data["messages"]   → OpenAI wire messages
#   .request_options    → model/stream/tools 等
#   .request_url        → API endpoint
# 通过 requester.request_model(request_data) 发起 SSE 流
```

**桥接要点：**
- 本框架的 `AgentlyChatBackend` 复用 Agently 的 requester 作为"网络传输层"
- 不使用 Agently 的 PromptGenerator（`Prompt.to_messages()`）来映射 prompt，因为 SDK Agent 的 tool loop 需要完整的 OpenAI wire `messages[]`（含 tool_call_id 等字段），PromptGenerator 会丢失这些字段
- 解析阶段使用 SDK 的 `ChatCompletionsSseParser`，确保 tool_calls delta 拼接口径与 SDK 一致

### 2.1.2 TriggerFlow 工作流编排

```python
from agently import TriggerFlow, TriggerFlowEventData

flow = TriggerFlow()

@flow.chunk
def step_a(data: TriggerFlowEventData):
    return {"result": "from step_a"}

@flow.chunk
def step_b(data: TriggerFlowEventData):
    return {"result": "from step_b"}

# 顺序执行
flow.to(step_a).to(step_b).end()

# 条件分支
flow.to(classify).match() \
    .case("type_a").to(handle_a) \
    .case("type_b").to(handle_b) \
    .case_else().to(handle_default) \
    .end_match().end()

# 循环（for_each）
flow.to(prepare_list).for_each(process_item).end()

# 启动执行
result = flow.start(initial_value)

# 异步流式执行
for event in flow.get_runtime_stream("start", timeout=None):
    print(event)
```

**TriggerFlow 核心能力清单：**
- `to()` — 顺序连接 chunk
- `when(event)` — 事件触发
- `if_condition() / elif_condition() / else_condition()` — 条件分支
- `match() / case() / case_else()` — 模式匹配
- `for_each()` — 集合迭代
- `batch()` — 批量并发
- concurrency semaphore — 并发控制
- `flow_data` — 全局状态（跨 chunk 共享）
- `runtime_data` — 执行级状态

**桥接策略（两条路径）：**
- **路径 A（当前）**：TriggerFlow 作为 SDK Agent 的 tool（`triggerflow_run_flow`），Agent 决定何时触发 flow
- **路径 B（未来）**：TriggerFlow 作为顶层编排器，每个 chunk 内调用 `CapabilityRuntime.run()` 执行一个 Agent

### 2.1.3 结构化输出

```python
result = agent.input("分析这个选题").output({
    "score": (int, "0-100 的评分"),
    "analysis": (str, "分析说明"),
    "tags": [(str, "标签")]
}).start(ensure_keys=["score", "analysis", "tags[*]"])
```

**桥接要点：**
- 结构化输出是 Agently 的独有能力，SDK Agent 不具备
- 本框架可以在 AgentAdapter 中，利用 Agently 的 `output()` 构造 system prompt 中的输出指令，然后注入到 SDK Agent 的 `initial_history`
- 但不做深度映射（避免破坏 SDK 的 tool loop wire messages 不变量）

### 2.1.4 Prompt 管理

```python
# Agently 的 Prompt 可以生成 OpenAI wire messages
messages = agent.input("...").info("...").instruct("...").output({...})
wire_messages = agent.create_request().generate_request_data().data["messages"]
```

**桥接要点：**
- 业务层可以用 Agently 的 Prompt API 构造 wire messages，然后通过 `initial_history` 注入 SDK Agent
- 本框架提供此通道但不强制使用

## 2.2 skills-runtime-sdk 0.1.1 关键 API

### 2.2.1 Agent 执行引擎

```python
from pathlib import Path
from agent_sdk import Agent
from agent_sdk.core.contracts import AgentEvent

# 构造 Agent
agent = Agent(
    workspace_root=Path("."),
    backend=my_chat_backend,        # 需注入 ChatBackend 实现
    config_paths=[Path("config/runtime.yaml")],
    env_vars={},
    human_io=my_human_io,            # 可选：HumanIOProvider
    approval_provider=my_approvals,  # 可选：ApprovalProvider
    cancel_checker=lambda: False,    # 可选：取消检查
)

# 同步运行
result = agent.run("请执行任务")
# result.status: "completed" | "failed" | "cancelled"
# result.final_output: str
# result.events_path: str (events.jsonl 路径)

# 流式运行
for event in agent.run_stream("请执行任务"):
    # event: AgentEvent
    # event.type: "run_started" | "llm_request_started" | "llm_response_delta"
    #           | "tool_call_requested" | "tool_call_started" | "tool_call_finished"
    #           | "skill_injected" | "run_completed" | "run_failed" | "run_cancelled"
    pass

# 异步流式运行
async for event in agent.run_stream_async("请执行任务", run_id="r1", initial_history=[...]):
    pass
```

**Agent 执行引擎的内部循环：**

```
1. build_messages(task, tools, skills, history) → wire messages
2. backend.stream_chat(model, messages, tools) → ChatStreamEvent 流
3. 若 finish_reason == "tool_calls":
   a. 对每个 tool_call: registry.dispatch(call) → ToolResult
   b. 把 ToolResult 追加到 history
   c. 回到步骤 2（新一轮 LLM 调用）
4. 若 finish_reason == "stop":
   a. 收集 assistant_text 作为 final_output
   b. 发出 run_completed 事件
   c. 返回
```

**关键不变量（本框架必须维持）：**
- wire `messages[]` 必须原样透传（含 tool_call_id、function.name 等字段）
- tool dispatch 由 SDK ToolRegistry 负责，本框架不干预
- WAL（events.jsonl）由 SDK 写入，本框架只消费（聚合为 NodeReport）

### 2.2.2 ChatBackend 接口

```python
from agent_sdk.core.agent import ChatBackend
from agent_sdk.llm.chat_sse import ChatStreamEvent
from agent_sdk.tools.protocol import ToolSpec

class ChatBackend(Protocol):
    async def stream_chat(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[ToolSpec]] = None,
    ) -> AsyncIterator[ChatStreamEvent]:
        """发起 streaming chat 并 yield 事件。"""
        ...

# ChatStreamEvent 类型：
# - type="text_delta", text="..."
# - type="tool_calls", tool_calls=[ToolCall(...)], finish_reason="tool_calls"
# - type="completed", finish_reason="stop"|"tool_calls"
```

**这就是桥接的核心接口。** 本框架的 `AgentlyChatBackend` 实现此接口，内部使用 Agently requester 发送 HTTP 请求。

### 2.2.3 SkillsManager

```python
from agent_sdk.skills.manager import SkillsManager

# preflight：零 I/O 配置预检
issues = skills_manager.preflight()
# 返回 List[FrameworkIssue]，生产环境下有 issue 应拒绝启动

# scan：扫描并加载 skills
skills = skills_manager.scan()
# 返回 List[Skill]，每个 Skill 有 skill_name/description/body_loader 等

# resolve_mentions：从 task 文本中解析 skill 引用
resolved = skills_manager.resolve_mentions("请使用 [$story-template] 生成故事")
# 返回 List[Tuple[Skill, Mention]]
```

### 2.2.4 ToolRegistry

```python
from agent_sdk.tools.registry import ToolRegistry
from agent_sdk.tools.protocol import ToolSpec, ToolCall, ToolResult

# 注册 tool
registry.register(spec=tool_spec, handler=tool_handler)

# 列出 specs（用于发送给 LLM）
specs: List[ToolSpec] = registry.list_specs()

# dispatch（执行 tool 调用）
result: ToolResult = registry.dispatch(tool_call, turn_id="t1", step_id="s1")
```

### 2.2.5 AgentEvent 结构

```python
@dataclass
class AgentEvent:
    type: str           # 事件类型
    ts: str             # RFC3339 时间戳
    run_id: str         # 运行 ID
    turn_id: str = ""   # 轮次 ID
    step_id: str = ""   # 步骤 ID
    payload: Dict[str, Any] = field(default_factory=dict)
```

**事件类型全集：**
| 事件类型 | 含义 | payload 关键字段 |
|---------|------|----------------|
| `run_started` | 运行开始 | {} |
| `llm_request_started` | LLM 请求开始 | model, messages_count, tools_count |
| `llm_response_delta` | LLM 流式输出 | delta_type, text |
| `tool_call_requested` | LLM 请求调用 tool | call_id, tool, arguments |
| `tool_call_started` | Tool 开始执行 | call_id, tool |
| `tool_call_finished` | Tool 执行完成 | call_id, tool, result |
| `skill_injected` | Skill 注入 | skill_name, skill_path, source |
| `approval_requested` | 请求审批 | key, tool, category |
| `approval_decided` | 审批决定 | key, decision |
| `run_completed` | 运行完成 | final_output, events_path |
| `run_failed` | 运行失败 | error, category |
| `run_cancelled` | 运行取消 | reason |

---

# 第三部分：完整架构设计

## 3.1 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                    业务层（宿主应用）                           │
│   声明 AgentSpec/SkillSpec/WorkflowSpec → 注册到 Runtime      │
│   调用 runtime.run(capability_id) → 获取 CapabilityResult    │
└───────────────────────────┬─────────────────────────────────┘
                            │ register / run
┌───────────────────────────┴─────────────────────────────────┐
│               能力组织层 (Capability Organization)             │
│                                                               │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐ │
│  │ Protocol     │  │ Runtime      │  │ Adapters             │ │
│  │              │  │              │  │                      │ │
│  │ CapabilitySpec│  │ Engine       │  │ AgentAdapter ────────┼─┼──→ Bridge
│  │ SkillSpec    │  │ Registry     │  │ WorkflowAdapter ─────┼─┼──→ TriggerFlow
│  │ AgentSpec    │  │ Guards       │  │ SkillAdapter ────────┼─┼──→ SDK SkillsManager
│  │ WorkflowSpec │  │ LoopCtrl     │  │                      │ │
│  │ ExecContext  │  │              │  │                      │ │
│  └─────────────┘  └──────────────┘  └──────────────────────┘ │
│                                                               │
├───────────────────────────────────────────────────────────────┤
│               桥接层 (Bridge)                                  │
│                                                               │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────┐ │
│  │AgentlyChatBackend│  │TriggerFlowTool   │  │NodeReport  │ │
│  │(Agently requester│  │(flow → SDK tool)  │  │Builder     │ │
│  │ → SDK ChatBackend│  │                  │  │            │ │
│  │ 接口实现)         │  │                  │  │            │ │
│  └────────┬─────────┘  └────────┬─────────┘  └─────┬──────┘ │
│           │                     │                   │        │
├───────────┴─────────────────────┴───────────────────┴────────┤
│               上游层                                           │
│                                                               │
│  Agently 4.0.7              skills-runtime-sdk 0.1.1          │
│  ┌────────────────┐         ┌──────────────────────┐         │
│  │ OpenAI         │         │ Agent Engine          │         │
│  │ Compatible     │         │ (run_stream_async)    │         │
│  │ Requester      │◄────────│                      │         │
│  │                │ inject  │ ToolRegistry          │         │
│  │ TriggerFlow    │ backend │ SkillsManager         │         │
│  │ (编排 DSL)     │         │ WAL (events.jsonl)    │         │
│  └────────────────┘         └──────────────────────┘         │
└───────────────────────────────────────────────────────────────┘
```

## 3.2 数据流：从业务声明到 LLM 执行

以业务场景"执行 MA-013 单角色设计师"为例，完整数据流：

```
1. 业务声明：
   AgentSpec(
       base=CapabilitySpec(id="MA-013", kind=AGENT, name="单角色设计师"),
       skills=["story-template"],
       loop_compatible=True,
       input_schema=AgentIOSchema(fields={"角色定位": "str", "故事梗概": "str"}),
       output_schema=AgentIOSchema(fields={"角色小传": "str"}),
   )

2. 注册：
   runtime.register(agent_spec)

3. 调用：
   result = await runtime.run("MA-013", input={"角色定位": "女主...", "故事梗概": "..."})

4. Engine 内部：
   a. Registry.get_or_raise("MA-013") → 找到 AgentSpec
   b. 创建 ExecutionContext(depth=current+1, bag=input)
   c. 分发到 AgentAdapter.execute(spec=agent_spec, input=..., context=...)

5. AgentAdapter 内部：
   a. 从 AgentSpec 构造 task 文本（含输入参数和输出格式要求）
   b. 如果 spec.skills 非空，从 Registry 找到对应 SkillSpec，加载内容
   c. 构造 initial_history（可选：注入 Agently 生成的 system prompt）
   d. 调用 BridgeRuntime.run_async(task, initial_history=...) ← 委托桥接层

6. 桥接层（AgentlySkillsRuntime）内部：
   a. 构造 SDK Agent，注入 AgentlyChatBackend
   b. SDK Agent.run_stream_async(task) 开始执行
   c. SDK Agent 内部循环：
      - build_messages → AgentlyChatBackend.stream_chat() → Agently requester → LLM API
      - LLM 返回 text → final_output
      - LLM 返回 tool_calls → ToolRegistry.dispatch() → 继续循环
   d. 产出 AgentEvent 流 → NodeReportBuilder 聚合为 NodeReport

7. 结果回传：
   AgentAdapter 包装为 CapabilityResult(status=SUCCESS, output="角色小传内容", report=node_report)
   → Engine 返回给业务层
```

## 3.3 数据流：Workflow 编排

以业务场景"执行 WF-001D 人物塑造子流程"为例：

```
WF-001D 声明：
  WorkflowSpec(
      base=CapabilitySpec(id="WF-001D", kind=WORKFLOW, name="人物塑造子流程"),
      steps=[
          Step(id="s1", capability=CapabilityRef(id="MA-013A")),
          LoopStep(id="s2", capability=CapabilityRef(id="MA-013"),
                   iterate_over="step.s1.角色列表",
                   max_iterations=20),
          Step(id="s3", capability=CapabilityRef(id="MA-014"),
               input_mappings=[InputMapping(source="step.s2", target_field="角色小传列表")]),
          LoopStep(id="s4", capability=CapabilityRef(id="MA-015"),
                   iterate_over="step.s2",
                   max_iterations=20),
      ],
  )

执行流：
  1. Engine.run("WF-001D", context_bag={"故事梗概": "..."})
  2. → WorkflowAdapter.execute()
  3. → Step s1: Engine._execute("MA-013A") → AgentAdapter → Bridge → LLM
       输出: {"角色列表": [{"定位": "女主..."}, {"定位": "男主..."}]}
  4. → LoopStep s2: LoopController 遍历 context.resolve_mapping("step.s1.角色列表")
       对每个角色: Engine._execute("MA-013", input=角色) → AgentAdapter → Bridge → LLM
       收集: [角色小传1, 角色小传2, ...]
       Guards.tick() 每次循环 +1，超限抛 LoopBreakerError
  5. → Step s3: Engine._execute("MA-014", input={"角色小传列表": [...]})
  6. → LoopStep s4: 同 s2，对每个角色调用 MA-015
  7. → 构造最终 CapabilityResult 返回
```

---

# 第四部分：Protocol 层完整规格

> Protocol 层是纯类型定义，不依赖任何上游模块。使用 Python dataclass + Enum。

## 4.1 capability.py — 统一能力接口

### 设计意图
三种元能力（Skill/Agent/Workflow）共享的公共类型。任何能力都有 id、kind、name，执行后都返回 CapabilityResult。

### 完整定义

```python
"""三种元能力共享的统一接口。"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class CapabilityKind(str, Enum):
    """能力种类。"""
    SKILL = "skill"
    AGENT = "agent"
    WORKFLOW = "workflow"


@dataclass(frozen=True)
class CapabilityRef:
    """
    能力引用——在组合中引用另一个能力。
    
    用于 Workflow 的 Step 中指定要调用的能力，
    或 Agent 的 collaborators/callable_workflows 中声明依赖。
    
    参数：
    - id: 被引用能力的唯一 ID
    - kind: 可选的类型提示（用于校验，不设则运行时从 Registry 推断）
    """
    id: str
    kind: Optional[CapabilityKind] = None


@dataclass(frozen=True)
class CapabilitySpec:
    """
    能力声明的公共字段。
    
    不作为基类继承，而是组合进具体 Spec（SkillSpec.base / AgentSpec.base / WorkflowSpec.base）。
    这样做是因为 SkillSpec/AgentSpec/WorkflowSpec 有各自独立的字段，
    用组合比继承更清晰（避免菱形继承和属性混淆）。
    
    参数：
    - id: 全局唯一 ID（如 "MA-013"、"WF-001D"）
    - kind: 能力种类（skill/agent/workflow）
    - name: 人类可读名称（如 "单角色设计师"）
    - description: 描述（可为空）
    - version: 语义化版本（默认 "0.1.0"）
    - tags: 标签列表（用于分类和搜索）
    - metadata: 自由扩展字段（框架不解读，业务可用于存储额外信息）
    """
    id: str
    kind: CapabilityKind
    name: str
    description: str = ""
    version: str = "0.1.0"
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class CapabilityStatus(str, Enum):
    """能力执行状态。"""
    PENDING = "pending"       # 等待执行
    RUNNING = "running"       # 执行中
    SUCCESS = "success"       # 执行成功
    FAILED = "failed"         # 执行失败
    CANCELLED = "cancelled"   # 被取消


@dataclass
class CapabilityResult:
    """
    所有能力执行后返回此结构。
    
    这是框架最核心的"出口类型"——业务层通过此结构获取执行结果。
    
    参数：
    - status: 执行状态
    - output: 执行输出（类型由具体能力决定，通常是 dict 或 str）
    - error: 错误信息（仅 FAILED 时非 None）
    - report: 执行报告（可选，通常是 NodeReport 或嵌套的子报告列表）
    - artifacts: 产出的文件路径列表（如生成的图片、视频等）
    - duration_ms: 执行耗时（毫秒，可选）
    - metadata: 扩展信息
    """
    status: CapabilityStatus
    output: Any = None
    error: Optional[str] = None
    report: Optional[Any] = None
    artifacts: List[str] = field(default_factory=list)
    duration_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
```

## 4.2 skill.py — Skills 声明

### 设计意图
Skill 是最小的能力单元——一段可被 Agent 消费的知识或指令。它可以是一个文件（如 SKILL.md）、一段内联文本、或一个 URI 资源。Skill 自身不执行 LLM 调用，而是被注入到 Agent 的 prompt context 中。

### 完整定义

```python
"""Skills 元能力声明。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from .capability import CapabilitySpec, CapabilityRef


@dataclass(frozen=True)
class SkillDispatchRule:
    """
    调度规则——Skill 可通过规则主动调度其他能力。
    
    这使 Skill 不仅是被动知识，还可以触发后续行为。
    例如：当选题评分低于 60 分时，自动调用"选题优化 Agent"。
    
    参数：
    - condition: 触发条件表达式（由 Adapter 评估，Phase 1 支持简单的 key 存在性检查）
    - target: 目标能力引用
    - priority: 优先级（数值越大越优先，同优先级按声明顺序）
    - metadata: 扩展信息
    """
    condition: str
    target: CapabilityRef
    priority: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillSpec:
    """
    Skills 声明。
    
    参数：
    - base: 公共能力字段
    - source: Skill 内容来源
      · source_type="file" 时：文件路径（相对于 workspace_root）
      · source_type="inline" 时：直接包含的文本内容
      · source_type="uri" 时：资源 URI（默认禁用，需 allowlist 授权）
    - source_type: "file" | "inline" | "uri"（默认 "file"）
    - dispatch_rules: 调度规则列表
    - inject_to: 声明自动注入到哪些 Agent（Agent ID 列表）
      · 当某 Agent 被执行时，如果有 Skill 声明了 inject_to 包含该 Agent 的 ID，
        则 Adapter 自动将该 Skill 的内容注入到 Agent 的 context 中
      · 与 AgentSpec.skills 是双向绑定的两种方式：
        Agent.skills = ["skill-A"] → Agent 主动声明使用 skill-A
        Skill.inject_to = ["agent-B"] → Skill 主动声明注入到 agent-B
        两者去重合并，以 Agent.skills 顺序优先
    """
    base: CapabilitySpec
    source: str
    source_type: str = "file"
    dispatch_rules: List[SkillDispatchRule] = field(default_factory=list)
    inject_to: List[str] = field(default_factory=list)
```

## 4.3 agent.py — Agent 声明

### 设计意图
Agent 是执行 LLM 调用的能力单元。它声明了使用哪些 Skills、哪些 Tools、可以协作的其他 Agent、可以调用的 Workflow，以及输入输出的结构。

### 完整定义

```python
"""Agent 元能力声明。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from .capability import CapabilitySpec, CapabilityRef


@dataclass(frozen=True)
class AgentIOSchema:
    """
    轻量 IO schema——描述 Agent 的输入/输出字段。
    
    不做深度类型校验（那是业务层的事），只做"字段存在性"的最小约束。
    
    参数：
    - fields: 字段名 → 类型描述（如 {"synopsis": "str", "score": "int"}）
    - required: 必填字段列表
    """
    fields: Dict[str, str] = field(default_factory=dict)
    required: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentSpec:
    """
    Agent 声明。
    
    参数：
    - base: 公共能力字段
    - skills: 装载的 Skill ID 列表（执行时会从 Registry 加载对应 SkillSpec 的内容注入 context）
    - tools: 注册的 Tool 名称列表（由宿主通过 SDK ToolRegistry 注册，这里只是声明引用）
    - collaborators: 可协作的其他 Agent 引用（用于 Registry 依赖校验）
    - callable_workflows: 可调用的 Workflow 引用（用于 Registry 依赖校验）
    - input_schema: 输入 schema（可选）
    - output_schema: 输出 schema（可选）
    - loop_compatible: 是否可被 LoopStep 循环调用（默认 False；标记为 True 表示此 Agent 设计为可重入的）
    - llm_config: LLM 覆盖配置（如特定 Agent 使用不同模型，不设则继承全局）
    - prompt_template: 可选的 prompt 模板（字符串模板，支持 {input_field} 占位符）
    - system_prompt: 可选的 system prompt（直接注入 messages[0]）
    """
    base: CapabilitySpec
    skills: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    collaborators: List[CapabilityRef] = field(default_factory=list)
    callable_workflows: List[CapabilityRef] = field(default_factory=list)
    input_schema: Optional[AgentIOSchema] = None
    output_schema: Optional[AgentIOSchema] = None
    loop_compatible: bool = False
    llm_config: Optional[Dict[str, Any]] = None
    prompt_template: Optional[str] = None
    system_prompt: Optional[str] = None
```

## 4.4 workflow.py — Workflow 声明

### 设计意图
Workflow 是编排多个能力的执行计划。它由一系列 Step 组成，支持顺序执行、循环、并行、条件分支。Workflow 本身不执行 LLM 调用，而是编排其他 Agent/Skill/Workflow 的执行。

### 步骤间的数据传递机制

Workflow 的核心挑战是步骤间的数据传递。本框架通过 `InputMapping` + `ExecutionContext` 实现：

```
Step s1 输出: {"角色列表": [...]}  → 存入 context.step_outputs["s1"]
Step s2 的 input_mapping: source="step.s1.角色列表" → 从 context 读取
```

支持 6 种映射前缀：
- `context.{key}` — 从全局 context bag 读取
- `previous.{key}` — 从上一步输出读取
- `step.{step_id}.{key}` — 从指定步骤输出读取
- `literal.{value}` — 字面量
- `item` — 循环中当前元素（整体）
- `item.{key}` — 循环中当前元素的字段

### 完整定义

```python
"""Workflow 元能力声明。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from .capability import CapabilitySpec, CapabilityRef


@dataclass(frozen=True)
class InputMapping:
    """
    输入映射——定义步骤输入字段的数据来源。
    
    参数：
    - source: 数据源表达式（见上述 6 种前缀）
    - target_field: 目标输入字段名
    """
    source: str
    target_field: str


@dataclass(frozen=True)
class Step:
    """
    基础步骤——执行单个能力。
    
    参数：
    - id: 步骤 ID（在 Workflow 内唯一，用于 step_outputs 引用）
    - capability: 要调用的能力引用
    - input_mappings: 输入映射列表（从 context 构造输入参数）
    """
    id: str
    capability: CapabilityRef
    input_mappings: List[InputMapping] = field(default_factory=list)


@dataclass(frozen=True)
class LoopStep:
    """
    循环步骤——对集合中每个元素执行能力。
    
    对应业务场景：MA-006 对每个候选选题评分、MA-013 对每个角色设计小传、
    MA-021 对每个章节扩写、MA-024 对每集编写剧本等。
    
    参数：
    - id: 步骤 ID
    - capability: 每次循环调用的能力引用
    - iterate_over: 数据源表达式（解析后应为 List）
    - item_input_mappings: 循环内的输入映射（可用 "item" / "item.{key}" 前缀）
    - max_iterations: 单步最大循环次数（防止无限循环）
    - collect_as: 结果收集字段名（存入 step_outputs[step_id][collect_as]）
    - fail_strategy: 失败策略
      · "abort" — 任一迭代失败立即中止（默认）
      · "skip" — 跳过失败项，继续后续迭代
      · "collect" — 收集所有结果（含失败），最终由业务判断
    """
    id: str
    capability: CapabilityRef
    iterate_over: str
    item_input_mappings: List[InputMapping] = field(default_factory=list)
    max_iterations: int = 100
    collect_as: str = "results"
    fail_strategy: str = "abort"


@dataclass(frozen=True)
class ParallelStep:
    """
    并行步骤——同时执行多个能力。
    
    对应业务场景：WF-001A 中 MA-001/002/003 并行执行市场分析。
    
    参数：
    - id: 步骤 ID
    - branches: 并行执行的步骤列表
    - join_strategy: 汇聚策略
      · "all_success" — 全部成功才视为成功（默认）
      · "any_success" — 任一成功即视为成功
      · "best_effort" — 收集所有结果，不因部分失败而中止
    """
    id: str
    branches: List[Union[Step, LoopStep]] = field(default_factory=list)
    join_strategy: str = "all_success"


@dataclass(frozen=True)
class ConditionalStep:
    """
    条件步骤——根据条件选择执行路径。
    
    参数：
    - id: 步骤 ID
    - condition_source: 条件值的数据源表达式（解析后用作 branches 的 key）
    - branches: 条件值 → 步骤的映射
    - default: 无匹配时的默认步骤（可选）
    """
    id: str
    condition_source: str
    branches: Dict[str, Union[Step, LoopStep]] = field(default_factory=dict)
    default: Optional[Union[Step, LoopStep]] = None


# 步骤联合类型
WorkflowStep = Union[Step, LoopStep, ParallelStep, ConditionalStep]


@dataclass(frozen=True)
class WorkflowSpec:
    """
    Workflow 声明。
    
    参数：
    - base: 公共能力字段
    - steps: 步骤列表（按声明顺序执行，除非是 ParallelStep）
    - context_schema: 初始 context bag 的 schema（可选，用于文档和校验）
    - output_mappings: 输出映射（从 context/step_outputs 构造最终输出）
    """
    base: CapabilitySpec
    steps: List[WorkflowStep] = field(default_factory=list)
    context_schema: Optional[Dict[str, str]] = None
    output_mappings: List[InputMapping] = field(default_factory=list)
```

## 4.5 context.py — 执行上下文

### 设计意图
ExecutionContext 是贯穿整个执行链的状态容器。它追踪调用链（防止无限递归）、管理步骤间的数据传递、控制递归深度。

### 完整定义

```python
"""执行上下文——跨能力状态传递和调用链管理。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class RecursionLimitError(Exception):
    """嵌套深度超限。当 Agent A 调用 Workflow B 调用 Agent C ... 层级超过 max_depth 时抛出。"""
    pass


@dataclass
class ExecutionContext:
    """
    执行上下文。
    
    每次 Engine._execute() 调用时，会创建一个 child context（depth+1），
    确保嵌套调用有独立的 step_outputs 空间，同时共享 bag 数据（浅拷贝）。
    
    参数：
    - run_id: 本次执行的顶层运行 ID（全局唯一，用于关联日志和报告）
    - parent_context: 父上下文（用于追溯调用链）
    - depth: 当前嵌套深度（从 0 开始）
    - max_depth: 最大嵌套深度（超过时 child() 抛 RecursionLimitError）
    - bag: 全局数据袋（浅拷贝传递，步骤间共享数据的主要方式）
    - step_outputs: 当前层级的步骤输出缓存（step_id → output）
    - call_chain: 调用链记录（能力 ID 列表，用于错误诊断）
    """
    run_id: str
    parent_context: Optional[ExecutionContext] = None
    depth: int = 0
    max_depth: int = 10
    bag: Dict[str, Any] = field(default_factory=dict)
    step_outputs: Dict[str, Any] = field(default_factory=dict)
    call_chain: List[str] = field(default_factory=list)

    def child(self, capability_id: str) -> ExecutionContext:
        """
        创建子上下文。
        
        行为：
        - depth + 1
        - bag 浅拷贝（子 context 可修改自己的 bag 而不影响父级）
        - step_outputs 清空（子 context 有独立的步骤输出空间）
        - call_chain 追加当前 capability_id
        - 如果 depth + 1 > max_depth，抛出 RecursionLimitError
        """
        if self.depth + 1 > self.max_depth:
            raise RecursionLimitError(
                f"Recursion depth {self.depth + 1} exceeds max {self.max_depth}. "
                f"Call chain: {self.call_chain + [capability_id]}"
            )
        return ExecutionContext(
            run_id=self.run_id,
            parent_context=self,
            depth=self.depth + 1,
            max_depth=self.max_depth,
            bag=dict(self.bag),
            step_outputs={},
            call_chain=self.call_chain + [capability_id],
        )

    def resolve_mapping(self, expression: str) -> Any:
        """
        解析映射表达式，从 context 中提取数据。
        
        支持的前缀：
        - "context.{key}" → self.bag[key]
        - "previous.{key}" → 最后一个 step_output 的 [key]
        - "step.{step_id}.{key}" → self.step_outputs[step_id][key]
        - "step.{step_id}" → self.step_outputs[step_id]（整体）
        - "literal.{value}" → 字面量字符串
        - "item" → self.bag["__current_item__"]（循环中当前元素）
        - "item.{key}" → self.bag["__current_item__"][key]
        
        找不到时返回 None（不抛异常，由调用方决定如何处理）。
        """
        if expression.startswith("context."):
            key = expression[len("context."):]
            return self.bag.get(key)
        
        elif expression.startswith("previous."):
            key = expression[len("previous."):]
            if not self.step_outputs:
                return None
            last_key = list(self.step_outputs.keys())[-1]
            last_out = self.step_outputs[last_key]
            if isinstance(last_out, dict):
                return last_out.get(key)
            return None
        
        elif expression.startswith("step."):
            rest = expression[len("step."):]
            parts = rest.split(".", 1)
            step_id = parts[0]
            key = parts[1] if len(parts) > 1 else None
            out = self.step_outputs.get(step_id)
            if key is None:
                return out
            if isinstance(out, dict):
                return out.get(key)
            return None
        
        elif expression.startswith("literal."):
            return expression[len("literal."):]
        
        elif expression == "item":
            return self.bag.get("__current_item__")
        
        elif expression.startswith("item."):
            key = expression[len("item."):]
            item = self.bag.get("__current_item__")
            if isinstance(item, dict):
                return item.get(key)
            return None
        
        return None
```

---

# 第五部分：Runtime 层完整规格

> Runtime 层不依赖上游。它只做"组织"——注册、校验、调度、保护。

## 5.1 registry.py — 能力注册表

### 设计意图
Registry 是所有能力的"电话簿"。业务注册 Spec 后，Engine 通过 Registry 查找和校验。

### 完整定义

```python
"""能力注册表——所有 Spec 的中央存储和查询。"""
from __future__ import annotations
from typing import Dict, List, Optional, Set, Union
from ..protocol.capability import CapabilityKind, CapabilitySpec
from ..protocol.skill import SkillSpec
from ..protocol.agent import AgentSpec
from ..protocol.workflow import WorkflowSpec, Step, LoopStep, ParallelStep, ConditionalStep

AnySpec = Union[SkillSpec, AgentSpec, WorkflowSpec]


def _get_base(spec: AnySpec) -> CapabilitySpec:
    """从具体 Spec 中提取公共 base。"""
    return spec.base


class CapabilityRegistry:
    """
    能力注册表。
    
    线程安全说明：当前为单线程设计（asyncio 单事件循环）。
    如未来需要多线程访问，需加锁。
    """

    def __init__(self) -> None:
        self._store: Dict[str, AnySpec] = {}

    def register(self, spec: AnySpec) -> None:
        """
        注册一个能力。
        
        行为：
        - 以 base.id 为 key 存储
        - 重复注册同一 ID 会覆盖（last-write-wins）
        """
        base = _get_base(spec)
        self._store[base.id] = spec

    def get(self, capability_id: str) -> Optional[AnySpec]:
        """查找能力，不存在返回 None。"""
        return self._store.get(capability_id)

    def get_or_raise(self, capability_id: str) -> AnySpec:
        """查找能力，不存在抛 KeyError。"""
        spec = self.get(capability_id)
        if spec is None:
            raise KeyError(f"Capability not found: {capability_id!r}")
        return spec

    def list_all(self) -> List[AnySpec]:
        """列出所有已注册能力。"""
        return list(self._store.values())

    def list_by_kind(self, kind: CapabilityKind) -> List[AnySpec]:
        """列出指定种类的所有能力。"""
        return [s for s in self._store.values() if _get_base(s).kind == kind]

    def list_ids(self) -> List[str]:
        """列出所有已注册能力的 ID。"""
        return list(self._store.keys())

    def has(self, capability_id: str) -> bool:
        """检查能力是否已注册。"""
        return capability_id in self._store

    def unregister(self, capability_id: str) -> bool:
        """注销能力，返回是否存在并已删除。"""
        if capability_id in self._store:
            del self._store[capability_id]
            return True
        return False

    def validate_dependencies(self) -> List[str]:
        """
        校验所有能力的依赖是否已注册。
        
        检查范围：
        - AgentSpec.skills 中引用的 Skill ID
        - AgentSpec.collaborators / callable_workflows 中引用的能力 ID
        - WorkflowSpec 中所有 Step/LoopStep 的 capability.id
        - WorkflowSpec 中 ParallelStep.branches 内的步骤
        - WorkflowSpec 中 ConditionalStep.branches/default 内的步骤
        - SkillSpec.dispatch_rules 中引用的 target.id
        
        返回：缺失的 ID 列表（空列表表示全部满足）
        """
        missing: Set[str] = set()
        
        for spec in self._store.values():
            if isinstance(spec, AgentSpec):
                for skill_id in spec.skills:
                    if skill_id not in self._store:
                        missing.add(skill_id)
                for ref in spec.collaborators:
                    if ref.id not in self._store:
                        missing.add(ref.id)
                for ref in spec.callable_workflows:
                    if ref.id not in self._store:
                        missing.add(ref.id)
            
            elif isinstance(spec, WorkflowSpec):
                self._collect_step_deps(spec.steps, missing)
            
            elif isinstance(spec, SkillSpec):
                for rule in spec.dispatch_rules:
                    if rule.target.id not in self._store:
                        missing.add(rule.target.id)
        
        return sorted(missing)

    def _collect_step_deps(self, steps: list, missing: Set[str]) -> None:
        """递归收集步骤中的能力依赖。"""
        for step in steps:
            if isinstance(step, (Step, LoopStep)):
                if step.capability.id not in self._store:
                    missing.add(step.capability.id)
            elif isinstance(step, ParallelStep):
                for branch in step.branches:
                    if isinstance(branch, (Step, LoopStep)):
                        if branch.capability.id not in self._store:
                            missing.add(branch.capability.id)
            elif isinstance(step, ConditionalStep):
                for branch in step.branches.values():
                    if isinstance(branch, (Step, LoopStep)):
                        if branch.capability.id not in self._store:
                            missing.add(branch.capability.id)
                if step.default and isinstance(step.default, (Step, LoopStep)):
                    if step.default.capability.id not in self._store:
                        missing.add(step.default.capability.id)

    def find_skills_injecting_to(self, agent_id: str) -> List[SkillSpec]:
        """查找所有声明了 inject_to 包含指定 agent_id 的 SkillSpec。"""
        result = []
        for spec in self._store.values():
            if isinstance(spec, SkillSpec) and agent_id in spec.inject_to:
                result.append(spec)
        return result
```

## 5.2 guards.py — 执行守卫

```python
"""执行守卫——全局循环和递归保护。"""
from __future__ import annotations


class LoopBreakerError(Exception):
    """全局循环迭代次数超限。"""
    pass


class ExecutionGuards:
    """
    全局执行守卫。
    
    作用：防止全局范围内的循环迭代总次数超限。
    这是 LoopStep.max_iterations 之上的第二道防线——
    即使每个 LoopStep 都设了合理的 max_iterations，
    多个 LoopStep 嵌套时总次数仍可能爆炸。
    
    例如：WF-001G 中 MA-024×60集 × MA-026×20镜头 × MA-027×20镜头 = 24000+ 次调用。
    ExecutionGuards 可以设一个总上限（如 50000）来兜底。
    """

    def __init__(self, *, max_total_loop_iterations: int = 50000):
        self._max = max_total_loop_iterations
        self._counter = 0

    def tick(self) -> None:
        """每次循环迭代调用一次。超限抛 LoopBreakerError。"""
        self._counter += 1
        if self._counter > self._max:
            raise LoopBreakerError(
                f"Global loop iteration limit ({self._max}) exceeded. "
                f"Total iterations so far: {self._counter}"
            )

    @property
    def counter(self) -> int:
        """当前累计迭代次数。"""
        return self._counter

    def reset(self) -> None:
        """重置计数器（通常在新的顶层 run 时调用）。"""
        self._counter = 0
```

## 5.3 loop.py — 循环控制器

```python
"""循环控制器——封装 LoopStep 的执行逻辑。"""
from __future__ import annotations
import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional
from ..protocol.capability import CapabilityResult, CapabilityStatus
from .guards import ExecutionGuards


class LoopController:
    """
    循环控制器。
    
    职责：
    - 遍历集合，对每个元素调用 execute_fn
    - 尊重 max_iterations 限制
    - 每次迭代调用 guards.tick()（全局熔断）
    - 根据 fail_strategy 决定失败时的行为
    """

    def __init__(self, *, guards: ExecutionGuards):
        self._guards = guards

    async def run_loop(
        self,
        *,
        items: List[Any],
        max_iterations: int,
        execute_fn: Callable[[Any, int], Awaitable[CapabilityResult]],
        fail_strategy: str = "abort",
    ) -> CapabilityResult:
        """
        执行循环。
        
        参数：
        - items: 要遍历的集合
        - max_iterations: 最大迭代次数
        - execute_fn: 执行函数，签名 (item, index) -> CapabilityResult
        - fail_strategy: "abort" | "skip" | "collect"
        
        返回：
        - CapabilityResult，output 为结果列表
        """
        results: List[Any] = []
        errors: List[Dict[str, Any]] = []
        effective_max = min(max_iterations, len(items))
        
        for idx, item in enumerate(items[:effective_max]):
            self._guards.tick()
            
            try:
                result = await execute_fn(item, idx)
            except Exception as exc:
                result = CapabilityResult(
                    status=CapabilityStatus.FAILED,
                    error=f"Loop iteration {idx} exception: {exc}",
                )
            
            if result.status == CapabilityStatus.FAILED:
                if fail_strategy == "abort":
                    return CapabilityResult(
                        status=CapabilityStatus.FAILED,
                        output=results,
                        error=f"Loop aborted at iteration {idx}/{effective_max}: {result.error}",
                        metadata={"completed_iterations": idx, "total_planned": effective_max},
                    )
                elif fail_strategy == "skip":
                    errors.append({"index": idx, "error": result.error})
                    continue
                elif fail_strategy == "collect":
                    results.append({"status": "failed", "error": result.error, "index": idx})
                    continue
            
            results.append(result.output)
        
        final_status = CapabilityStatus.SUCCESS
        if errors and fail_strategy == "skip":
            final_status = CapabilityStatus.SUCCESS  # 跳过失败仍视为成功
        
        return CapabilityResult(
            status=final_status,
            output=results,
            metadata={
                "completed_iterations": len(results),
                "total_planned": effective_max,
                "skipped_errors": errors if errors else None,
            },
        )
```

## 5.4 engine.py — 能力运行时主入口

```python
"""CapabilityRuntime：能力组织层主入口。"""
from __future__ import annotations
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol
from ..protocol.capability import CapabilityKind, CapabilityResult, CapabilityStatus
from ..protocol.context import ExecutionContext, RecursionLimitError
from ..protocol.skill import SkillSpec
from ..protocol.agent import AgentSpec
from ..protocol.workflow import WorkflowSpec
from .registry import AnySpec, CapabilityRegistry, _get_base
from .guards import ExecutionGuards, LoopBreakerError
from .loop import LoopController


@dataclass(frozen=True)
class RuntimeConfig:
    """
    能力运行时配置。
    
    参数：
    - max_depth: 最大嵌套深度（ExectionContext.max_depth）
    - max_total_loop_iterations: 全局循环迭代上限（ExecutionGuards）
    - default_loop_max_iterations: LoopStep 默认 max_iterations
    """
    max_depth: int = 10
    max_total_loop_iterations: int = 50000
    default_loop_max_iterations: int = 200


class AdapterProtocol(Protocol):
    """Adapter 执行协议。所有 Adapter 必须实现此接口。"""
    async def execute(
        self,
        *,
        spec: Any,
        input: Dict[str, Any],
        context: ExecutionContext,
        runtime: CapabilityRuntime,
    ) -> CapabilityResult: ...


class CapabilityRuntime:
    """
    CapabilityRuntime：框架主入口。
    
    使用流程：
    1. 创建 runtime = CapabilityRuntime(config=RuntimeConfig())
    2. 注入 adapters: runtime.set_adapter(CapabilityKind.AGENT, my_agent_adapter)
    3. 注册能力: runtime.register(agent_spec)
    4. 校验依赖: missing = runtime.validate(); assert not missing
    5. 执行: result = await runtime.run("capability-id", input={...})
    """

    def __init__(self, *, config: RuntimeConfig = RuntimeConfig()):
        self.config = config
        self.registry = CapabilityRegistry()
        self._guards = ExecutionGuards(max_total_loop_iterations=config.max_total_loop_iterations)
        self._loop_controller = LoopController(guards=self._guards)
        self._adapters: Dict[CapabilityKind, AdapterProtocol] = {}

    # --- 配置 API ---

    def set_adapter(self, kind: CapabilityKind, adapter: AdapterProtocol) -> None:
        """注入指定种类的 Adapter。"""
        self._adapters[kind] = adapter

    # --- 注册 API ---

    def register(self, spec: AnySpec) -> None:
        """注册一个能力。"""
        self.registry.register(spec)

    def register_many(self, specs: List[AnySpec]) -> None:
        """批量注册能力。"""
        for spec in specs:
            self.registry.register(spec)

    # --- 校验 API ---

    def validate(self) -> List[str]:
        """校验所有依赖，返回缺失的能力 ID 列表。"""
        return self.registry.validate_dependencies()

    # --- 执行 API ---

    async def run(
        self,
        capability_id: str,
        *,
        input: Optional[Dict[str, Any]] = None,
        context_bag: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        max_depth: Optional[int] = None,
    ) -> CapabilityResult:
        """
        执行指定能力。
        
        参数：
        - capability_id: 能力 ID
        - input: 输入参数
        - context_bag: 初始 context bag（传递给 ExecutionContext.bag）
        - run_id: 运行 ID（不指定则自动生成）
        - max_depth: 最大嵌套深度（不指定则用 config.max_depth）
        
        返回：CapabilityResult
        """
        # 重置全局守卫（每次顶层 run 重新计数）
        self._guards.reset()
        
        spec = self.registry.get_or_raise(capability_id)
        
        ctx = ExecutionContext(
            run_id=run_id or uuid.uuid4().hex,
            max_depth=max_depth or self.config.max_depth,
            bag=dict(context_bag or {}),
        )
        
        start_time = time.monotonic()
        result = await self._execute(spec, input=input or {}, context=ctx)
        duration_ms = (time.monotonic() - start_time) * 1000
        result.duration_ms = duration_ms
        
        return result

    async def _execute(
        self,
        spec: AnySpec,
        *,
        input: Dict[str, Any],
        context: ExecutionContext,
    ) -> CapabilityResult:
        """
        内部执行——创建子 context，分发到 Adapter。
        
        此方法被 Engine 自身和 WorkflowAdapter 递归调用。
        """
        base = _get_base(spec)
        
        try:
            child_ctx = context.child(base.id)
        except RecursionLimitError as exc:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=str(exc),
                metadata={"error_type": "recursion_limit"},
            )
        
        adapter = self._adapters.get(base.kind)
        if adapter is None:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"No adapter registered for kind: {base.kind.value}",
                metadata={"error_type": "no_adapter"},
            )
        
        try:
            return await adapter.execute(
                spec=spec, input=input, context=child_ctx, runtime=self,
            )
        except LoopBreakerError as exc:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=str(exc),
                metadata={"error_type": "loop_breaker"},
            )
        except Exception as exc:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"Adapter execution error: {exc}",
                metadata={"error_type": "adapter_error", "exception_class": type(exc).__name__},
            )

    # --- 供 Adapter 使用的内部 API ---

    @property
    def loop_controller(self) -> LoopController:
        """供 WorkflowAdapter 使用的循环控制器。"""
        return self._loop_controller

    @property
    def guards(self) -> ExecutionGuards:
        """供 Adapter 使用的全局守卫。"""
        return self._guards
```

---

# 第六部分：Adapter 层完整规格

> Adapter 是唯一允许 import 上游的层。它负责把 Protocol 声明翻译为上游 API 调用。

## 6.1 agent_adapter.py — Agent 适配器

### 设计意图
AgentAdapter 把 AgentSpec 的声明式调用翻译为对桥接层 `AgentlySkillsRuntime` 的真实执行。它是 Protocol → Bridge 的关键枢纽。

### 关键行为

1. **构造 task 文本**：从 input 参数和 AgentSpec 的 prompt_template/system_prompt 构造 LLM 任务描述
2. **加载并注入 Skills**：合并 spec.skills + inject_to 匹配的 skills，从 Registry 获取 SkillSpec，加载内容
3. **委托桥接层执行**：调用 `bridge_runtime.run_async(task, initial_history=...)` 
4. **包装返回值**：把 NodeResultV2 转为 CapabilityResult

### 完整定义

```python
"""Agent 适配器：AgentSpec → Bridge Runtime 执行。"""
from __future__ import annotations
import json
from typing import Any, Callable, Awaitable, Dict, List, Optional
from ..protocol.agent import AgentSpec
from ..protocol.capability import CapabilityResult, CapabilityStatus
from ..protocol.context import ExecutionContext
from ..protocol.skill import SkillSpec


class AgentAdapter:
    """
    Agent 适配器。
    
    参数：
    - runner: 异步执行函数。签名：
        async def runner(task: str, *, initial_history: Optional[List] = None) -> Any
      通常传入 AgentlySkillsRuntime.run_async。
    - skill_content_loader: 可选的 Skill 内容加载函数。签名：
        def loader(spec: SkillSpec) -> str
      用于从 SkillSpec 加载实际内容文本。
      如果不提供，则 skill 注入只使用 spec.source 字段。
    """

    def __init__(
        self,
        *,
        runner: Optional[Callable[..., Awaitable[Any]]] = None,
        skill_content_loader: Optional[Callable[[SkillSpec], str]] = None,
    ):
        self._runner = runner
        self._skill_content_loader = skill_content_loader

    async def execute(
        self,
        *,
        spec: AgentSpec,
        input: Dict[str, Any],
        context: ExecutionContext,
        runtime: Any,  # CapabilityRuntime（避免循环 import）
    ) -> CapabilityResult:
        if self._runner is None:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error="AgentAdapter: no runner injected. "
                      "Inject AgentlySkillsRuntime.run_async or a compatible async callable.",
            )

        # 1. 合并 Skills（spec.skills + inject_to 匹配）
        skill_ids = list(spec.skills)
        if hasattr(runtime, 'registry'):
            injecting_skills = runtime.registry.find_skills_injecting_to(spec.base.id)
            for s in injecting_skills:
                if s.base.id not in skill_ids:
                    skill_ids.append(s.base.id)

        # 2. 加载 Skill 内容
        skill_contents: List[str] = []
        for sid in skill_ids:
            if hasattr(runtime, 'registry'):
                skill_spec = runtime.registry.get(sid)
                if isinstance(skill_spec, SkillSpec):
                    if self._skill_content_loader:
                        content = self._skill_content_loader(skill_spec)
                    else:
                        content = skill_spec.source
                    skill_contents.append(f"[Skill: {skill_spec.base.name}]\n{content}")

        # 3. 构造 task 文本
        task = self._build_task(spec=spec, input=input, skill_contents=skill_contents)

        # 4. 构造 initial_history（如有 system_prompt）
        initial_history = None
        if spec.system_prompt:
            initial_history = [{"role": "system", "content": spec.system_prompt}]

        # 5. 委托桥接层执行
        try:
            result = await self._runner(task, initial_history=initial_history)
        except Exception as exc:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"Agent execution error: {exc}",
            )

        # 6. 包装返回值
        return self._wrap_result(result)

    def _build_task(
        self,
        *,
        spec: AgentSpec,
        input: Dict[str, Any],
        skill_contents: List[str],
    ) -> str:
        """从 AgentSpec + input 构造 task 文本。"""
        parts: List[str] = []

        # prompt_template 优先
        if spec.prompt_template:
            try:
                task_text = spec.prompt_template.format(**input)
                parts.append(task_text)
            except KeyError:
                # 模板字段缺失时回退到序列化 input
                parts.append(spec.prompt_template)
                parts.append(f"\n输入参数:\n{json.dumps(input, ensure_ascii=False, indent=2)}")
        else:
            # 无模板时序列化 input
            if "task" in input:
                parts.append(str(input["task"]))
            else:
                parts.append(json.dumps(input, ensure_ascii=False, indent=2))

        # 注入 Skills
        if skill_contents:
            parts.append("\n\n--- 参考资料 ---")
            for content in skill_contents:
                parts.append(content)

        # 输出 schema 提示
        if spec.output_schema and spec.output_schema.fields:
            parts.append(f"\n\n请按以下格式输出 JSON：")
            schema_desc = json.dumps(
                {k: f"({v})" for k, v in spec.output_schema.fields.items()},
                ensure_ascii=False, indent=2,
            )
            parts.append(schema_desc)

        return "\n".join(parts)

    def _wrap_result(self, result: Any) -> CapabilityResult:
        """把桥接层返回值包装为 CapabilityResult。"""
        # 兼容 NodeResultV2
        if hasattr(result, "node_report"):
            nr = result.node_report
            output = getattr(result, "final_output", None)
            if output is None:
                output = nr.meta.get("final_output") if hasattr(nr, "meta") else None
            status = CapabilityStatus.SUCCESS if nr.status == "success" else CapabilityStatus.FAILED
            error = nr.reason if status == CapabilityStatus.FAILED else None
            return CapabilityResult(status=status, output=output, error=error, report=nr)
        
        # 兼容普通返回值
        if isinstance(result, str):
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output=result)
        if isinstance(result, dict):
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output=result)
        
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=result)
```

## 6.2 workflow_adapter.py — Workflow 适配器

### 设计意图
WorkflowAdapter 负责编排执行 WorkflowSpec 中的步骤序列。它调用 `runtime._execute()` 来执行每个步骤（递归回 Engine），从而实现 Workflow 内嵌 Agent、Agent 内嵌 Workflow 的能力。

### 关键行为
1. 遍历 steps，按类型分发到不同执行逻辑
2. Step → 解析 input_mappings，调用 runtime._execute
3. LoopStep → 委托 LoopController
4. ParallelStep → asyncio.gather 并行执行
5. ConditionalStep → 解析条件值，选择分支
6. 每步结果缓存到 context.step_outputs
7. 步骤失败 → 立即返回（或按配置继续）
8. 全部完成 → 解析 output_mappings 构造最终输出

### 完整定义

```python
"""Workflow 适配器：WorkflowSpec → 步骤编排执行。"""
from __future__ import annotations
import asyncio
from typing import Any, Dict, List
from ..protocol.workflow import (
    WorkflowSpec, Step, LoopStep, ParallelStep, ConditionalStep, InputMapping,
)
from ..protocol.capability import CapabilityResult, CapabilityStatus
from ..protocol.context import ExecutionContext


class WorkflowAdapter:
    """Workflow 适配器。不依赖任何上游——所有执行都通过 runtime._execute() 递归回 Engine。"""

    async def execute(
        self,
        *,
        spec: WorkflowSpec,
        input: Dict[str, Any],
        context: ExecutionContext,
        runtime: Any,  # CapabilityRuntime
    ) -> CapabilityResult:
        # 合并 input 到 context bag
        context.bag.update(input)

        for step in spec.steps:
            result = await self._execute_step(step, context=context, runtime=runtime)
            if result.status == CapabilityStatus.FAILED:
                return result

        # 构造最终输出
        output = self._resolve_output_mappings(spec.output_mappings, context)
        if output is None:
            # 无 output_mappings 时，返回所有 step_outputs
            output = dict(context.step_outputs)

        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=output)

    async def _execute_step(
        self, step: Any, *, context: ExecutionContext, runtime: Any,
    ) -> CapabilityResult:
        if isinstance(step, Step):
            return await self._execute_basic_step(step, context=context, runtime=runtime)
        elif isinstance(step, LoopStep):
            return await self._execute_loop_step(step, context=context, runtime=runtime)
        elif isinstance(step, ParallelStep):
            return await self._execute_parallel_step(step, context=context, runtime=runtime)
        elif isinstance(step, ConditionalStep):
            return await self._execute_conditional_step(step, context=context, runtime=runtime)
        else:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"Unknown step type: {type(step).__name__}",
            )

    async def _execute_basic_step(
        self, step: Step, *, context: ExecutionContext, runtime: Any,
    ) -> CapabilityResult:
        # 解析 input_mappings
        step_input = self._resolve_input_mappings(step.input_mappings, context)

        # 获取目标 spec 并执行
        target_spec = runtime.registry.get_or_raise(step.capability.id)
        result = await runtime._execute(target_spec, input=step_input, context=context)

        # 缓存结果
        context.step_outputs[step.id] = result.output
        return result

    async def _execute_loop_step(
        self, step: LoopStep, *, context: ExecutionContext, runtime: Any,
    ) -> CapabilityResult:
        # 解析要遍历的集合
        items = context.resolve_mapping(step.iterate_over)
        if not isinstance(items, list):
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"LoopStep '{step.id}': iterate_over resolved to {type(items).__name__}, expected list",
            )

        target_spec = runtime.registry.get_or_raise(step.capability.id)

        async def execute_item(item: Any, idx: int) -> CapabilityResult:
            # 设置当前循环项到 context bag
            item_context = ExecutionContext(
                run_id=context.run_id,
                parent_context=context,
                depth=context.depth,
                max_depth=context.max_depth,
                bag={**context.bag, "__current_item__": item},
                step_outputs=dict(context.step_outputs),
                call_chain=list(context.call_chain),
            )
            # 解析 item_input_mappings
            step_input = self._resolve_input_mappings(step.item_input_mappings, item_context)
            if not step_input:
                # 无映射时直接用 item 作为 input
                step_input = item if isinstance(item, dict) else {"item": item}
            return await runtime._execute(target_spec, input=step_input, context=item_context)

        result = await runtime.loop_controller.run_loop(
            items=items,
            max_iterations=step.max_iterations,
            execute_fn=execute_item,
            fail_strategy=step.fail_strategy,
        )

        context.step_outputs[step.id] = result.output
        return result

    async def _execute_parallel_step(
        self, step: ParallelStep, *, context: ExecutionContext, runtime: Any,
    ) -> CapabilityResult:
        tasks = []
        for branch in step.branches:
            tasks.append(self._execute_step(branch, context=context, runtime=runtime))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        branch_results = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                branch_results.append(CapabilityResult(
                    status=CapabilityStatus.FAILED, error=str(r),
                ))
            else:
                branch_results.append(r)

        # 根据 join_strategy 判断整体状态
        if step.join_strategy == "all_success":
            if any(r.status == CapabilityStatus.FAILED for r in branch_results):
                failed = [r for r in branch_results if r.status == CapabilityStatus.FAILED]
                return CapabilityResult(
                    status=CapabilityStatus.FAILED,
                    output=[r.output for r in branch_results],
                    error=f"ParallelStep '{step.id}': {len(failed)}/{len(branch_results)} branches failed",
                )
        elif step.join_strategy == "any_success":
            if not any(r.status == CapabilityStatus.SUCCESS for r in branch_results):
                return CapabilityResult(
                    status=CapabilityStatus.FAILED,
                    output=[r.output for r in branch_results],
                    error=f"ParallelStep '{step.id}': no branch succeeded",
                )

        context.step_outputs[step.id] = [r.output for r in branch_results]
        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output=[r.output for r in branch_results],
        )

    async def _execute_conditional_step(
        self, step: ConditionalStep, *, context: ExecutionContext, runtime: Any,
    ) -> CapabilityResult:
        condition_value = context.resolve_mapping(step.condition_source)
        condition_key = str(condition_value) if condition_value is not None else ""

        branch = step.branches.get(condition_key, step.default)
        if branch is None:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"ConditionalStep '{step.id}': no branch for condition '{condition_key}' and no default",
            )

        result = await self._execute_step(branch, context=context, runtime=runtime)
        context.step_outputs[step.id] = result.output
        return result

    def _resolve_input_mappings(
        self, mappings: List[InputMapping], context: ExecutionContext,
    ) -> Dict[str, Any]:
        result = {}
        for m in mappings:
            value = context.resolve_mapping(m.source)
            result[m.target_field] = value
        return result

    def _resolve_output_mappings(
        self, mappings: List[InputMapping], context: ExecutionContext,
    ) -> Any:
        if not mappings:
            return None
        result = {}
        for m in mappings:
            value = context.resolve_mapping(m.source)
            result[m.target_field] = value
        return result
```

## 6.3 skill_adapter.py — Skill 适配器

### 设计意图
SkillAdapter 负责加载 Skill 内容。Skill 自身不做 LLM 调用，但可以通过 dispatch_rules 触发其他能力。

```python
"""Skill 适配器：SkillSpec → 内容加载 + 可选 dispatch。"""
from __future__ import annotations
from typing import Any, Dict
from ..protocol.skill import SkillSpec
from ..protocol.capability import CapabilityResult, CapabilityStatus
from ..protocol.context import ExecutionContext


class SkillAdapter:
    """
    Skill 适配器。
    
    行为：
    1. 加载 Skill 内容（file/inline/uri）
    2. 检查 dispatch_rules（Phase 1 仅做简单条件评估）
    3. 返回内容作为 output
    """

    def __init__(self, *, workspace_root: str = "."):
        self._workspace_root = workspace_root

    async def execute(
        self,
        *,
        spec: SkillSpec,
        input: Dict[str, Any],
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        # 1. 加载内容
        try:
            content = self._load_content(spec)
        except Exception as exc:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"Skill content load error: {exc}",
            )

        # 2. 检查 dispatch_rules
        dispatched_results = []
        for rule in spec.dispatch_rules:
            if self._evaluate_condition(rule.condition, context):
                try:
                    target_spec = runtime.registry.get_or_raise(rule.target.id)
                    result = await runtime._execute(target_spec, input=input, context=context)
                    dispatched_results.append({"target": rule.target.id, "result": result.output})
                except Exception as exc:
                    dispatched_results.append({"target": rule.target.id, "error": str(exc)})

        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output=content,
            metadata={"dispatched": dispatched_results} if dispatched_results else {},
        )

    def _load_content(self, spec: SkillSpec) -> str:
        if spec.source_type == "inline":
            return spec.source
        elif spec.source_type == "file":
            import os
            path = os.path.join(self._workspace_root, spec.source)
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        elif spec.source_type == "uri":
            raise NotImplementedError("URI loading requires allowlist authorization (safe-by-default)")
        else:
            raise ValueError(f"Unknown source_type: {spec.source_type}")

    def _evaluate_condition(self, condition: str, context: ExecutionContext) -> bool:
        """Phase 1: 简单条件评估——检查 context bag 中 key 是否存在且为 truthy。"""
        value = context.bag.get(condition)
        return bool(value)
```

---

# 第七部分：桥接层（已有代码，保持不动）

> 以下模块在 v0.3.0 中已实现并通过回归测试，本轮保持不动。

## 7.1 AgentlyChatBackend（adapters/agently_backend.py）
- 实现 SDK `ChatBackend` 接口
- 内部使用 Agently OpenAICompatible requester 发送 HTTP 请求
- 解析阶段使用 SDK `ChatCompletionsSseParser`
- **不变量：wire `messages[]` 原样透传**

## 7.2 TriggerFlowTool（adapters/triggerflow_tool.py）
- 注册 `triggerflow_run_flow` 为 SDK Agent 的 tool
- 执行时需要 `HumanIOProvider` 审批（生产默认 fail-closed）
- 审批结果和执行结果写入 WAL 证据链

## 7.3 AgentlySkillsRuntime（bridge.py，原 runtime.py）
- 桥接层主入口
- 构造 SDK Agent，注入 AgentlyChatBackend
- 提供 preflight gate（error/warn/off）
- 提供 upstream fork 校验（off/warn/strict）
- 运行并聚合事件为 NodeReport v2
- **这是 AgentAdapter 的 runner 实际调用的对象**

## 7.4 NodeReportBuilder（reporting/node_report.py）
- 从 SDK AgentEvent 流聚合结构化报告
- 支持 status 推断（success/failed/needs_approval/incomplete）

## 7.5 类型（types.py）
- NodeReportV2 / NodeResultV2 控制面强结构

## 7.6 配置（config.py）
- BridgeConfigModel（Pydantic）
- AgentlySkillsRuntimeConfig

---

# 第八部分：业务集成示例

> 以下示例展示业务层如何使用框架声明和编排能力。

## 8.1 声明 Agent（MA-013 单角色设计师）

```python
from agently_skills_runtime import (
    CapabilityRuntime, RuntimeConfig, CapabilityKind,
    CapabilitySpec, AgentSpec, AgentIOSchema,
)

ma_013 = AgentSpec(
    base=CapabilitySpec(
        id="MA-013",
        kind=CapabilityKind.AGENT,
        name="单角色设计师",
        description="设计单个角色的完整人物小传",
        tags=["TP2", "人物"],
    ),
    skills=["character-template"],
    input_schema=AgentIOSchema(
        fields={"角色定位": "str", "故事梗概": "str"},
        required=["角色定位", "故事梗概"],
    ),
    output_schema=AgentIOSchema(
        fields={"角色小传": "str"},
        required=["角色小传"],
    ),
    loop_compatible=True,
    prompt_template=(
        "你是一位专业的角色设计师。请根据以下信息设计一个完整的角色小传。\n\n"
        "角色定位：{角色定位}\n\n"
        "故事梗概：{故事梗概}\n\n"
        "请输出完整的角色小传，包括：外貌特征、性格特点、背景故事、核心矛盾、角色弧线。"
    ),
)
```

## 8.2 声明 Workflow（WF-001D 人物塑造子流程）

```python
from agently_skills_runtime import (
    WorkflowSpec, CapabilitySpec, CapabilityKind, CapabilityRef,
    Step, LoopStep, ParallelStep, InputMapping,
)

wf_001d = WorkflowSpec(
    base=CapabilitySpec(
        id="WF-001D",
        kind=CapabilityKind.WORKFLOW,
        name="人物塑造子流程",
        description="MA-013A → [MA-013×N] → MA-014 → [MA-015×N]",
    ),
    steps=[
        # Step 1: 角色定位规划
        Step(
            id="plan",
            capability=CapabilityRef(id="MA-013A"),
            input_mappings=[
                InputMapping(source="context.故事梗概", target_field="故事梗概"),
            ],
        ),
        # Step 2: 循环设计每个角色
        LoopStep(
            id="design",
            capability=CapabilityRef(id="MA-013"),
            iterate_over="step.plan.角色列表",
            item_input_mappings=[
                InputMapping(source="item.定位", target_field="角色定位"),
                InputMapping(source="context.故事梗概", target_field="故事梗概"),
            ],
            max_iterations=20,
            collect_as="角色小传列表",
        ),
        # Step 3: 角色关系架构
        Step(
            id="relations",
            capability=CapabilityRef(id="MA-014"),
            input_mappings=[
                InputMapping(source="step.design", target_field="角色小传列表"),
            ],
        ),
        # Step 4: 循环视觉化每个角色
        LoopStep(
            id="visual",
            capability=CapabilityRef(id="MA-015"),
            iterate_over="step.design",
            item_input_mappings=[
                InputMapping(source="item", target_field="角色小传"),
            ],
            max_iterations=20,
        ),
    ],
    output_mappings=[
        InputMapping(source="step.design", target_field="角色小传列表"),
        InputMapping(source="step.relations", target_field="角色关系图谱"),
        InputMapping(source="step.visual", target_field="视觉关键词列表"),
    ],
)
```

## 8.3 注册并执行

```python
import asyncio
from agently_skills_runtime import CapabilityRuntime, RuntimeConfig, CapabilityKind
from agently_skills_runtime.adapters.agent_adapter import AgentAdapter
from agently_skills_runtime.adapters.workflow_adapter import WorkflowAdapter

async def main():
    # 1. 创建桥接层 runtime（已有代码）
    bridge_rt = create_bridge_runtime(...)  # AgentlySkillsRuntime

    # 2. 创建能力运行时
    runtime = CapabilityRuntime(config=RuntimeConfig(max_depth=10))

    # 3. 注入 Adapters
    runtime.set_adapter(CapabilityKind.AGENT, AgentAdapter(runner=bridge_rt.run_async))
    runtime.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())

    # 4. 注册所有能力
    runtime.register_many([ma_013a, ma_013, ma_014, ma_015, wf_001d])

    # 5. 校验依赖
    missing = runtime.validate()
    assert not missing, f"Missing capabilities: {missing}"

    # 6. 执行
    result = await runtime.run("WF-001D", context_bag={"故事梗概": "一个关于..."})
    print(result.status)      # SUCCESS
    print(result.output)      # {"角色小传列表": [...], "角色关系图谱": ..., "视觉关键词列表": [...]}

asyncio.run(main())
```

---

# 第九部分：包结构与模块命名

## 9.1 处理命名冲突

v0.3.0 中已有 `src/agently_skills_runtime/runtime.py`（桥接层主入口）。新增的 `runtime/` 目录与之冲突。

**解决方案：将已有的 `runtime.py` 重命名为 `bridge.py`。**

理由：
- `bridge.py` 更准确地表达了该模块的角色（桥接层主入口）
- `runtime/` 目录给能力运行时层（Engine/Registry/Guards/Loop）
- 只需更新 `__init__.py` 的 import 路径和测试中的 import

## 9.2 最终包结构

```
src/agently_skills_runtime/
├── __init__.py                     # 公共 API 导出（Bridge + Protocol + Runtime）
├── bridge.py                       # AgentlySkillsRuntime（原 runtime.py，重命名）
├── types.py                        # NodeReportV2 / NodeResultV2
├── config.py                       # BridgeConfigModel / AgentlySkillsRuntimeConfig
├── errors.py                       # 框架错误定义
│
├── protocol/                       # 能力协议（纯类型，不依赖上游）
│   ├── __init__.py
│   ├── capability.py
│   ├── skill.py
│   ├── agent.py
│   ├── workflow.py
│   └── context.py
│
├── runtime/                        # 能力运行时（不依赖上游）
│   ├── __init__.py
│   ├── engine.py                   # CapabilityRuntime
│   ├── registry.py                 # CapabilityRegistry
│   ├── loop.py                     # LoopController
│   └── guards.py                   # ExecutionGuards + LoopBreakerError
│
├── adapters/                       # 适配器
│   ├── __init__.py
│   ├── agently_backend.py          # AgentlyChatBackend（已有 ✅）
│   ├── triggerflow_tool.py         # TriggerFlowTool（已有 ✅）
│   ├── upstream.py                 # 上游 fork 校验（已有 ✅）
│   ├── agent_adapter.py            # AgentAdapter（新增）
│   ├── workflow_adapter.py         # WorkflowAdapter（新增）
│   └── skill_adapter.py            # SkillAdapter（新增）
│
└── reporting/                      # 执行报告（已有 ✅）
    ├── __init__.py
    └── node_report.py
```

## 9.3 pyproject.toml 变更

```toml
[project]
name = "agently-skills-runtime"
version = "0.4.0"
description = "Capability-oriented bridge framework for Agently + Skills Runtime SDK."
requires-python = ">=3.10"
dependencies = [
  "agently",
  "skills-runtime-sdk",
  "PyYAML",
]

[project.optional-dependencies]
dev = ["pytest>=7", "pytest-asyncio>=0.23"]
```

---

# 第十部分：测试策略

## 10.1 测试分层

| 层级 | 目录 | 依赖上游？ | 覆盖范围 |
|------|------|-----------|---------|
| Protocol 单测 | `tests/protocol/` | ❌ 不依赖 | 类型构造、context 映射、递归限制 |
| Runtime 单测 | `tests/runtime/` | ❌ 不依赖 | Registry CRUD、Guards tick、Loop 控制、Engine 分发 |
| Adapter 单测 | `tests/adapters/` | ❌ mock runner | AgentAdapter/WorkflowAdapter/SkillAdapter |
| 场景测试 | `tests/scenarios/` | ❌ 全 mock | 模拟 WF-001D 等完整流程 |
| 桥接层测试 | `tests/` (已有) | ✅ 需上游 | AgentlySkillsRuntime + 真实 SDK Agent |

## 10.2 关键测试用例

### Protocol 层
- `test_context_resolve_mapping_6_prefixes` — 6 种前缀全覆盖
- `test_context_child_depth_limit` — 递归深度超限
- `test_workflow_spec_construction` — 复杂 Workflow 声明

### Runtime 层
- `test_registry_register_and_get` — 注册和查询
- `test_registry_validate_dependencies_missing` — 缺失依赖检测
- `test_registry_find_skills_injecting_to` — inject_to 查询
- `test_guards_tick_normal_and_exceed` — 全局熔断
- `test_loop_controller_normal` — 正常循环
- `test_loop_controller_abort_on_failure` — 失败中止
- `test_loop_controller_skip_on_failure` — 失败跳过
- `test_engine_dispatch_to_adapter` — mock adapter 分发
- `test_engine_no_adapter_returns_failed` — 无 adapter 处理
- `test_engine_recursion_limit` — 递归超限

### Adapter 层
- `test_agent_adapter_with_mock_runner` — 正常执行
- `test_agent_adapter_no_runner` — 无 runner 返回 FAILED
- `test_agent_adapter_skill_injection` — Skills 注入
- `test_workflow_adapter_sequential` — 顺序执行
- `test_workflow_adapter_loop` — 循环执行
- `test_workflow_adapter_parallel` — 并行执行
- `test_workflow_adapter_conditional` — 条件分支

### 场景测试
- `test_scenario_wf001d_character_creation` — 模拟 WF-001D
- `test_scenario_nested_workflow` — Workflow 内嵌 Workflow

## 10.3 验收标准

1. `pip install -e .` 成功
2. `pytest -q` 全部通过（已有桥接层测试不受影响）
3. Protocol + Runtime 测试不需要上游（纯离线）
4. 以下代码可运行：

```python
from agently_skills_runtime import (
    CapabilityRuntime, RuntimeConfig, CapabilityKind,
    CapabilitySpec, AgentSpec, WorkflowSpec,
    Step, LoopStep, CapabilityRef, InputMapping,
)

# 桥接层导出不变
from agently_skills_runtime import AgentlySkillsRuntime, NodeReportV2, NodeResultV2
```
