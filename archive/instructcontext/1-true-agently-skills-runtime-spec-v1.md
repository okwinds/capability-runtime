# agently-skills-runtime 框架规格书 v1.1

> 本文档包含：战略共识总结、仓库现状审计、差距分析、完整框架规格。
> 目标：仅凭本文档即可复刻整套框架。

---

# 第一部分：战略共识总结

## 1.1 核心范式：面向能力的 AI 代理框架

我们确立了一个根本性的认知转变：**从面向对象到面向能力（Capability-Oriented）**。

`agently-skills-runtime` 是一个通用的、轻量的"面向能力"AI 代理框架。它通过桥接适配器形式聚合上游 Agently（agent 构建 + workflow 编排）和 skills-runtime-sdk（skills 驱动 + tools/approvals/WAL），向业务层提供三种对等的元能力原语：

- **Skills**：知识性能力——可发现、可注入的指导性原则和行为规范
- **Agent**：智能性能力——具有自主决策能力的执行体
- **Workflow**：结构性能力——确定性的、可重复的编排流程

**三者是对等的、可互相嵌套的元能力，不是层级关系。**

## 1.2 互嵌关系

```
Skills 可以：通过指导性原则调度 Agent 和 Workflow
Agent 可以：装载 Skills 定义自身能力，调用 Workflow 作为原子能力，与其他 Agent 协作
Workflow 可以：编排 Agent、Skills-driven Agent、多 Agent 节点作为原子步骤
```

## 1.3 框架边界

**框架只做三件事：让能力可以被声明、被执行、被组合。**

框架**不关心**：
- 执行结果要不要给人看（业务决定）
- 人看完要不要修改（业务决定）
- 修改完再不再执行下一步（业务决定）
- 任何与人相关的流程编排（业务决定）

框架的职责是：接收输入 → 执行能力 → 返回结果。业务层拿到结果后自行决定后续流程。

## 1.4 框架原则

| 原则 | 说明 |
|------|------|
| 不侵入上游 | 不 fork Agently 和 skills-runtime-sdk，通过桥接适配 |
| 随上游进化 | 上游能力增强时，框架通过更新适配器同步增强 |
| 通用不绑业务 | 框架不包含任何特定业务逻辑，不预设使用场景 |
| 轻量灵活 | 概念最少化，业务开发者 30 分钟内可理解 |
| 能力收敛 | 业务层只需面对本框架，不需直接接触上游 |

## 1.5 完整架构分层

```
┌─────────────────────────────────────────────────┐
│  前端                                            │
├─────────────────── 服务契约 ────────────────────┤
│  业务服务端（REST/SSE, 持久化, 会话管理）          │
├─────────────────── 业务调用 ────────────────────┤
│  Agent Domain（业务能力实现层，用 S/A/W 声明）     │
├─────────────────── 框架 API ────────────────────┤
│  agently-skills-runtime（本框架）                 │
│  Capability Protocol + Adapters + Composition    │
├─────────────────── 桥接适配 ────────────────────┤
│  上游：Agently + skills-runtime-sdk              │
└─────────────────────────────────────────────────┘
```

本框架只负责中间一层。Agent Domain、业务服务端、前端不在本框架范围内。

业务层如果需要在流程中加入人工参与，可以在 Agent Domain 层自行编排——比如调 `runtime.run("step-1")` 拿到结果，展示给用户，用户修改后再调 `runtime.run("step-2", context_bag={"step1_result": modified})`。框架不需要知道中间有人参与。

## 1.6 实施路径：Hybrid

- Phase 1：最小能力协议（类型定义 + 互嵌规则）
- Phase 2：单场景验证（选 WF-001D 人物塑造子流程，覆盖 Workflow→Agent→Skills 嵌套 + 循环）
- Phase 3：协议修正 + 扩展
- Phase 4：完整 Agent Domain 建设

---

# 第二部分：仓库现状审计

## 2.1 仓库结构

```
agently-skills-runtime/
├── src/agently_skills_runtime/
│   ├── __init__.py                    # 包入口
│   ├── runtime.py                     # 主入口类 AgentlySkillsRuntime
│   ├── types.py                       # NodeReportV2, NodeResultV2
│   ├── config.py                      # BridgeConfigModel
│   ├── adapters/
│   │   ├── agently_backend.py         # AgentlyChatBackend（LLM 传输适配器）
│   │   └── triggerflow_tool.py        # triggerflow_run_flow tool
│   └── reporting/
│       └── node_report.py             # NodeReportBuilder
├── tests/
├── config/
├── projects/agently-skills-web-prototype/
└── pyproject.toml
```

## 2.2 各模块评估

### AgentlySkillsRuntime（runtime.py）— 旧主入口

**做了什么：** 接收 Agently agent + 配置，构造 SDK Agent，注入 AgentlyChatBackend，`run_async(task)` 执行单次任务返回 NodeReport。

**评估：** 本质是"单次 SDK Agent run 的包装器"。不支持多 Agent、Workflow 编排、循环。**需要完全重设计为"能力注册+组合+执行引擎"。**

### AgentlyChatBackend（agently_backend.py）— LLM 传输适配

**做了什么：** 实现 SDK `ChatBackend` 接口，通过 Agently OpenAICompatible requester 发送请求，用 SDK `ChatCompletionsSseParser` 解析响应。

**评估：** 设计良好的传输层适配器。**可保留，迁移为 Agent 元能力的底层 LLM 通道。**

### TriggerFlow Tool（triggerflow_tool.py）— Workflow 触发

**做了什么：** 注册 `triggerflow_run_flow` tool 让 Agent 触发 TriggerFlow。

**评估：** 方向需重新审视。新愿景中 Workflow 是独立元能力，不应仅作为 Agent 的 tool。**其中 approvals 证据链机制可参考。**

### NodeReport（types.py + node_report.py）— 可观测性

**做了什么：** 结构化执行报告，从 SDK AgentEvent 流聚合。

**评估：** 设计良好。**需扩展，覆盖 S/A/W 三种能力和嵌套调用链。**

## 2.3 总体评估

**可保留的资产：**
1. AgentlyChatBackend — LLM 传输适配
2. NodeReport 的设计理念 — 强结构化执行报告
3. Preflight gate 理念 — 启动前校验
4. BridgeConfigModel — 配置管理模式

**推倒重来：**
1. AgentlySkillsRuntime 主入口 → CapabilityRuntime
2. TriggerFlow 集成方式 → WorkflowAdapter
3. 整个 API 表面 → 基于三种元能力的声明式 API
4. types.py → protocol/ 下的类型定义

---

# 第三部分：差距分析

| 需要新建的能力 | 当前状态 | 需要做什么 |
|---------------|---------|-----------|
| Capability Protocol（统一能力协议） | 不存在 | 定义 S/A/W 共享的声明、执行、组合接口 |
| SkillSpec（Skills 声明） | SDK 有 Skills 但无声明式管理 | Skills 的注册、发现、与 Agent/Workflow 的绑定 |
| AgentSpec（Agent 声明） | 两个上游各自的 Agent 未统一 | 统一 Agent 声明，Skills 装载，能力定义 |
| WorkflowSpec（Workflow 声明） | TriggerFlow 作为 tool 存在 | 独立的 Workflow 声明，支持编排 Agent 节点 |
| Composition Runtime（组合运行时） | 不存在 | 处理互嵌的执行上下文、递归控制、能力解析 |
| CapabilityRegistry（能力注册表） | 不存在 | 全局能力注册、发现、依赖解析 |
| ExecutionContext（执行上下文） | 不存在 | 调用链追踪、状态传递、递归深度控制 |
| LoopController（循环控制） | 不存在 | 封装循环调用模式，含次数限制 |
| ExecutionReport（执行报告） | NodeReport 只覆盖单次 run | 扩展覆盖嵌套调用链 |

---

# 第四部分：完整框架规格

## 4.1 设计哲学

```
框架是一个"能力组合空间"的运行时。
它不执行业务逻辑，只负责：
1. 让能力可以被声明（是什么）
2. 让能力可以被执行（做什么）
3. 让能力可以互相组合（怎么组合）
```

## 4.2 包结构

```
agently-skills-runtime/
├── src/agently_skills_runtime/
│   ├── __init__.py                     # 公共 API 导出
│   │
│   ├── protocol/                       # 能力协议（核心，纯类型定义）
│   │   ├── __init__.py
│   │   ├── capability.py               # CapabilitySpec, CapabilityResult
│   │   ├── skill.py                    # SkillSpec, SkillDispatchRule
│   │   ├── agent.py                    # AgentSpec, AgentIOSchema
│   │   ├── workflow.py                 # WorkflowSpec, Step, LoopStep, ParallelStep, ConditionalStep
│   │   └── context.py                  # ExecutionContext, RecursionLimitError
│   │
│   ├── runtime/                        # 能力运行时（执行引擎）
│   │   ├── __init__.py
│   │   ├── engine.py                   # CapabilityRuntime — 主入口
│   │   ├── registry.py                 # CapabilityRegistry — 能力注册表
│   │   ├── loop.py                     # LoopController — 循环控制
│   │   └── guards.py                   # 递归深度限制、循环熔断
│   │
│   ├── adapters/                       # 上游适配器（桥接层）
│   │   ├── __init__.py
│   │   ├── skill_adapter.py            # SkillAdapter
│   │   ├── agent_adapter.py            # AgentAdapter
│   │   ├── workflow_adapter.py         # WorkflowAdapter
│   │   ├── llm_backend.py             # AgentlyChatBackend（迁移自旧代码）
│   │   └── upstream.py                 # 上游版本校验
│   │
│   ├── reporting/                      # 执行报告
│   │   ├── __init__.py
│   │   ├── report.py                   # ExecutionReport
│   │   └── builder.py                  # ReportBuilder
│   │
│   ├── config.py                       # 框架配置
│   └── errors.py                       # 框架错误定义
│
├── tests/
│   ├── protocol/
│   ├── runtime/
│   ├── adapters/
│   └── scenarios/
│
├── config/
│   └── default.yaml
├── pyproject.toml
└── README.md
```

## 4.3 能力协议（protocol/）

### 4.3.1 统一能力接口（capability.py）

```python
"""三种元能力共享的统一接口。"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime


class CapabilityKind(str, Enum):
    """能力种类。"""
    SKILL = "skill"
    AGENT = "agent"
    WORKFLOW = "workflow"


@dataclass(frozen=True)
class CapabilityRef:
    """能力引用——用于在组合中引用另一个能力。"""
    id: str
    kind: Optional[CapabilityKind] = None


@dataclass(frozen=True)
class CapabilitySpec:
    """
    能力声明的公共字段。
    组合进具体 Spec（SkillSpec.base / AgentSpec.base / WorkflowSpec.base），非基类继承。
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
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class CapabilityResult:
    """所有能力执行后返回此结构。"""
    status: CapabilityStatus
    output: Any = None
    error: Optional[str] = None
    report: Optional[Any] = None        # ExecutionReport
    artifacts: List[str] = field(default_factory=list)
```

### 4.3.2 Skills 声明（skill.py）

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
    condition: 触发条件（context bag key 或表达式）
    target: 目标能力引用
    """
    condition: str
    target: CapabilityRef
    priority: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillSpec:
    """
    Skills 声明。
    source_type: "file" | "inline" | "uri"
    dispatch_rules: 调度规则，使 Skills 具备主动调度能力
    inject_to: 声明此 Skill 应自动注入到哪些 Agent
    """
    base: CapabilitySpec
    source: str
    source_type: str = "file"
    dispatch_rules: List[SkillDispatchRule] = field(default_factory=list)
    inject_to: List[str] = field(default_factory=list)
```

### 4.3.3 Agent 声明（agent.py）

```python
"""Agent 元能力声明。"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from .capability import CapabilitySpec, CapabilityRef


@dataclass(frozen=True)
class AgentIOSchema:
    """轻量 IO schema。"""
    fields: Dict[str, str] = field(default_factory=dict)
    required: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentSpec:
    """
    Agent 声明。
    skills: 装载的 Skill ID 列表
    collaborators: 可协作的其他 Agent
    callable_workflows: 可调用的 Workflow
    loop_compatible: 是否支持被循环调用
    llm_config: LLM 配置覆盖（不设则继承全局）
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
```

### 4.3.4 Workflow 声明（workflow.py）

```python
"""Workflow 元能力声明。"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from .capability import CapabilitySpec, CapabilityRef


@dataclass(frozen=True)
class InputMapping:
    """
    输入映射。source 格式：
    - "context.{key}" — 从执行上下文 bag 获取
    - "previous.{key}" — 从上一步输出获取
    - "step.{step_id}.{key}" — 从指定步骤输出获取
    - "literal.{value}" — 字面量
    - "item" / "item.{key}" — 循环中当前元素
    """
    source: str
    target_field: str


@dataclass(frozen=True)
class Step:
    """基础步骤——执行单个能力。"""
    id: str
    capability: CapabilityRef
    input_mappings: List[InputMapping] = field(default_factory=list)


@dataclass(frozen=True)
class LoopStep:
    """循环步骤——对集合中每个元素执行能力。"""
    id: str
    capability: CapabilityRef
    iterate_over: str
    item_input_mappings: List[InputMapping] = field(default_factory=list)
    max_iterations: int = 100
    collect_as: str = "results"


@dataclass(frozen=True)
class ParallelStep:
    """并行步骤——同时执行多个能力。"""
    id: str
    branches: List[Union[Step, LoopStep]] = field(default_factory=list)
    join_strategy: str = "all_success"      # all_success | any_success | best_effort


@dataclass(frozen=True)
class ConditionalStep:
    """条件步骤——根据条件选择执行路径。"""
    id: str
    condition_source: str
    branches: Dict[str, Union[Step, LoopStep]] = field(default_factory=dict)
    default: Optional[Union[Step, LoopStep]] = None


WorkflowStep = Union[Step, LoopStep, ParallelStep, ConditionalStep]


@dataclass(frozen=True)
class WorkflowSpec:
    """Workflow 声明。"""
    base: CapabilitySpec
    steps: List[WorkflowStep] = field(default_factory=list)
    context_schema: Optional[Dict[str, str]] = None
    output_mappings: List[InputMapping] = field(default_factory=list)
```

### 4.3.5 执行上下文（context.py）

```python
"""执行上下文——跨能力的状态传递和调用链管理。"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class RecursionLimitError(Exception):
    """嵌套深度超限。"""
    pass


@dataclass
class ExecutionContext:
    """
    执行上下文——每次能力执行都在一个上下文中进行。

    职责：
    1. 追踪调用链（谁调用了谁）
    2. 管理递归深度
    3. 传递共享数据（context bag）
    4. 记录步骤输出（供后续步骤引用）
    """
    run_id: str
    parent_context: Optional[ExecutionContext] = None
    depth: int = 0
    max_depth: int = 10
    bag: Dict[str, Any] = field(default_factory=dict)
    step_outputs: Dict[str, Any] = field(default_factory=dict)
    call_chain: List[str] = field(default_factory=list)

    def child(self, capability_id: str) -> ExecutionContext:
        """创建子上下文。depth+1，bag 浅拷贝。超限抛 RecursionLimitError。"""
        if self.depth + 1 > self.max_depth:
            raise RecursionLimitError(
                f"Depth {self.depth + 1} > max {self.max_depth}. "
                f"Chain: {self.call_chain + [capability_id]}"
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
        解析映射表达式:
        - "context.{key}" → bag[key]
        - "previous.{key}" → 最后一个 step_output
        - "step.{step_id}.{key}" → step_outputs[step_id]
        - "literal.{value}" → 字面量
        - "item" / "item.{key}" → bag["__loop_item__"]
        """
        parts = expression.split(".", 1)
        prefix, rest = parts[0], (parts[1] if len(parts) > 1 else "")

        if prefix == "context":
            return _deep_get(self.bag, rest)
        elif prefix == "previous":
            last = self._last_step_output()
            return _deep_get(last, rest) if last is not None else None
        elif prefix == "step":
            sub = rest.split(".", 1)
            step_id, key = sub[0], (sub[1] if len(sub) > 1 else "")
            out = self.step_outputs.get(step_id)
            return _deep_get(out, key) if out is not None else None
        elif prefix == "literal":
            return rest
        elif prefix == "item":
            item = self.bag.get("__loop_item__")
            return _deep_get(item, rest) if rest and item is not None else item
        raise ValueError(f"Unknown mapping prefix: {prefix!r}")

    def _last_step_output(self) -> Any:
        if not self.step_outputs:
            return None
        return list(self.step_outputs.values())[-1]


def _deep_get(obj: Any, dotted_key: str) -> Any:
    """按点号路径从嵌套 dict 取值。"""
    if not dotted_key:
        return obj
    current = obj
    for k in dotted_key.split("."):
        if isinstance(current, dict):
            current = current.get(k)
        elif hasattr(current, k):
            current = getattr(current, k)
        else:
            return None
    return current
```

## 4.4 能力运行时（runtime/）

### 4.4.1 能力注册表（registry.py）

```python
"""能力注册表——全局能力的注册、发现、依赖解析。"""

from __future__ import annotations
from typing import Dict, List, Optional, Union
from ..protocol.capability import CapabilityKind
from ..protocol.skill import SkillSpec
from ..protocol.agent import AgentSpec
from ..protocol.workflow import WorkflowSpec

AnySpec = Union[SkillSpec, AgentSpec, WorkflowSpec]


class CapabilityRegistry:
    """
    能力注册表。

    - register(spec): 注册能力，重复 ID 覆盖
    - get(id) -> Optional[AnySpec]
    - get_or_raise(id) -> AnySpec, 不存在抛 KeyError
    - list_by_kind(kind) -> List[AnySpec]
    - validate_dependencies() -> List[str]: 校验所有引用的能力是否已注册

    validate_dependencies 需检查:
    - AgentSpec.skills 中每个 ID
    - AgentSpec.collaborators 和 callable_workflows 中每个 ref.id
    - WorkflowSpec.steps 中所有 Step/LoopStep 的 capability.id
    - ParallelStep.branches 中递归提取
    - ConditionalStep.branches + default 中递归提取
    """
```

### 4.4.2 主入口（engine.py）

```python
"""CapabilityRuntime——框架主入口。"""

# 核心 API:
#
# runtime = CapabilityRuntime(config=RuntimeConfig(...))
# runtime.register(spec)
# runtime.validate()
# result = await runtime.run(capability_id, input=..., context_bag=..., run_id=..., max_depth=10)
#
# 内部分发:
# - SkillSpec  → SkillAdapter.execute()
# - AgentSpec  → AgentAdapter.execute()
# - WorkflowSpec → WorkflowAdapter.execute()
#
# 所有嵌套调用回到 runtime._execute()，由 ExecutionContext 管理递归
```

**RuntimeConfig 字段：**
- `workspace_root: str` — 工作空间根目录
- `sdk_config_paths: List[str]` — SDK 配置路径列表
- `agently_agent: Any` — 宿主提供的 Agently agent 实例
- `preflight_mode: str` — "error" | "warn" | "off"
- `max_loop_iterations: int` — 全局循环次数上限（默认 200）
- `max_depth: int` — 全局嵌套深度上限（默认 10）

### 4.4.3 循环控制器（loop.py）

```python
"""循环控制器——封装循环调用模式。"""

# LoopController:
# - execute_loop(step: LoopStep, context, executor) -> CapabilityResult
#   1. context.resolve_mapping(step.iterate_over) 得到集合
#   2. 检查集合长度 <= min(step.max_iterations, global_max)
#   3. 对每个元素:
#      a. 注入 __loop_item__ 和 __loop_index__ 到 context.bag
#      b. 解析 item_input_mappings
#      c. 调用 executor(capability_id, input, context)
#   4. 收集结果到 {step.collect_as: [...]}
#   5. 单次迭代失败 → 终止循环，返回 partial_results + failed_at
```

### 4.4.4 执行守卫（guards.py）

```python
"""执行守卫——循环熔断。"""

# ExecutionGuards:
# - max_total_loop_iterations: int = 5000 (一次顶层 run 的全部循环总次数)
# - record_loop_iteration(): 超限抛 LoopBreakerError
#
# class LoopBreakerError(Exception): pass
```

## 4.5 上游适配器（adapters/）

### 4.5.1 LLM 传输（llm_backend.py）

从现有 `adapters/agently_backend.py` 直接迁移，保持功能不变：
- AgentlyChatBackend（实现 SDK ChatBackend 接口）
- AgentlyRequester / AgentlyRequesterFactory 协议
- build_openai_compatible_requester_factory 函数

### 4.5.2 SkillAdapter（skill_adapter.py）

```python
"""桥接 skills-runtime-sdk 的 Skills 能力。"""

# SkillAdapter:
# - execute(spec, input, context, runtime) -> CapabilityResult
#   有 dispatch_rules → 按优先级评估条件，匹配则委托 runtime._execute(target)
#   无 dispatch_rules → 加载内容并返回
# - load_for_injection(spec) -> str: 加载 Skill 内容供注入 Agent
# - _load_skill_content(spec): 按 source_type (file/inline/uri) 加载
# - _evaluate_condition(condition, input, context) -> bool: Phase 1 检查 bag key
```

### 4.5.3 AgentAdapter（agent_adapter.py）

```python
"""桥接 Agently + skills-runtime-sdk 的 Agent 能力。"""

# AgentAdapter:
# - execute(spec, input, context, runtime) -> CapabilityResult
#   1. 从 spec.skills 通过 SkillAdapter.load_for_injection 加载内容
#   2. 构造 task（Skills 内容 + input 组合）
#   3. 构造 SDK Agent，注入 AgentlyChatBackend 作为 LLM backend
#   4. 执行 Agent run，收集事件
#   5. 返回 CapabilityResult（output + report）
```

### 4.5.4 WorkflowAdapter（workflow_adapter.py）

```python
"""Workflow 编排执行。"""

# WorkflowAdapter:
# - execute(spec, input, context, runtime) -> CapabilityResult
#   1. 将 input 合并到 context.bag
#   2. 遍历 spec.steps，逐步执行:
#      - Step → 解析 input_mappings，调用 runtime._execute
#      - LoopStep → 委托 LoopController
#      - ParallelStep → asyncio.gather 并行执行各 branch
#      - ConditionalStep → 解析条件值，选择对应 branch
#   3. 每步结果缓存到 context.step_outputs[step.id]
#   4. 步骤失败 → 立即返回失败
#   5. 全部完成 → 解析 output_mappings 构造最终输出
```

## 4.6 公共 API 导出（__init__.py）

```python
# Protocol
from .protocol.capability import CapabilitySpec, CapabilityKind, CapabilityRef, CapabilityResult, CapabilityStatus
from .protocol.skill import SkillSpec, SkillDispatchRule
from .protocol.agent import AgentSpec, AgentIOSchema
from .protocol.workflow import WorkflowSpec, Step, LoopStep, ParallelStep, ConditionalStep, InputMapping, WorkflowStep
from .protocol.context import ExecutionContext, RecursionLimitError

# Runtime
from .runtime.engine import CapabilityRuntime, RuntimeConfig
from .runtime.registry import CapabilityRegistry
from .runtime.guards import LoopBreakerError
```

## 4.7 使用示例（面向业务层开发者）

```python
from agently_skills_runtime import (
    CapabilityRuntime, RuntimeConfig,
    CapabilitySpec, CapabilityKind, CapabilityRef,
    SkillSpec, AgentSpec, WorkflowSpec,
    Step, LoopStep, InputMapping,
)

# 1. 配置
config = RuntimeConfig(
    workspace_root=".",
    sdk_config_paths=["./config/sdk.yaml"],
    agently_agent=my_agently_agent,
)

# 2. 创建 runtime
runtime = CapabilityRuntime(config=config)

# 3. 注册 Skills
runtime.register(SkillSpec(
    base=CapabilitySpec(id="skill-guide", kind=CapabilityKind.SKILL, name="Guide"),
    source="skills/guide.md",
))

# 4. 注册 Agents
runtime.register(AgentSpec(
    base=CapabilitySpec(id="agent-planner", kind=CapabilityKind.AGENT, name="Planner"),
    skills=["skill-guide"],
))
runtime.register(AgentSpec(
    base=CapabilitySpec(id="agent-worker", kind=CapabilityKind.AGENT, name="Worker"),
    skills=["skill-guide"],
    loop_compatible=True,
))

# 5. 注册 Workflow
runtime.register(WorkflowSpec(
    base=CapabilitySpec(id="wf-main", kind=CapabilityKind.WORKFLOW, name="Main"),
    steps=[
        Step(
            id="plan",
            capability=CapabilityRef(id="agent-planner"),
            input_mappings=[InputMapping(source="context.task", target_field="task")],
        ),
        LoopStep(
            id="work",
            capability=CapabilityRef(id="agent-worker"),
            iterate_over="step.plan.items",
            item_input_mappings=[InputMapping(source="item", target_field="item")],
            max_iterations=50,
            collect_as="results",
        ),
    ],
))

# 6. 校验 + 执行
runtime.validate()

import asyncio
result = asyncio.run(runtime.run("wf-main", context_bag={"task": "do something"}))
print(result.status, result.output)
```

**业务层如需在步骤间加入人工参与：**

```python
# 业务层自行编排，框架不感知
result_step1 = await runtime.run("agent-planner", input={"task": "..."})

# 展示给用户，用户修改...
user_modified = show_to_user_and_get_feedback(result_step1.output)

# 带着修改后的结果继续
result_step2 = await runtime.run("wf-work-loop", context_bag={"plan": user_modified})
```

---

# 第五部分：实施计划

## Phase 1（1-2 周）：协议 + 骨架

- [ ] 实现 protocol/ 全部类型定义（5 个文件）
- [ ] 实现 runtime/registry.py（注册表 + 依赖校验）
- [ ] 实现 runtime/engine.py 骨架（register + validate + run 的分发逻辑）
- [ ] 实现 protocol/context.py（执行上下文 + 映射解析）
- [ ] 实现 runtime/guards.py（循环守卫）
- [ ] 单元测试：协议层 + 注册表 + 上下文映射
- [ ] 迁移现有 AgentlyChatBackend 到 adapters/llm_backend.py

## Phase 2（2-3 周）：适配器 + 场景验证

- [ ] 实现 adapters/skill_adapter.py（Skill 加载 + 注入）
- [ ] 实现 adapters/agent_adapter.py（SDK Agent 构造 + 执行）
- [ ] 实现 adapters/workflow_adapter.py（步骤执行器 + 循环 + 并行）
- [ ] 实现 runtime/loop.py（循环控制器）
- [ ] 选择验证场景，端到端跑通
- [ ] 集成测试

## Phase 3（1-2 周）：修正 + 扩展

- [ ] 根据 Phase 2 反馈修正协议和适配器
- [ ] 扩展更多验证场景
- [ ] 执行报告的完整实现
- [ ] 文档和示例

---

*文档版本：v1.1 | 日期：2026-02-18*
*变更：v1.0 → v1.1 移除所有框架层人机交互定义，人机交互完全由业务层负责*
