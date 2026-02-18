# Codex Task: 重构 agently-skills-runtime 框架

## 你的角色
你是一个资深 AI 全栈工程师，精通 Python 异步编程、框架设计、软件架构。你现在要在已有仓库 `okwinds/agently-skills-runtime` 上进行一次完整的架构重构。

---

## 一、项目背景（必读）

### 这个框架是什么
`agently-skills-runtime` 是一个"面向能力"的 AI 代理框架。它通过桥接适配器形式聚合两个上游开源项目的能力：
- **Agently**（/home/gavin/workspaces/codes/Agently ）：提供 agent 构建 + TriggerFlow workflow 编排 + LLM 传输层
- **skills-runtime-sdk**（/home/gavin/workspaces/codes/skills-runtime-sdk ）：提供 skills 驱动 + tools/approvals/WAL/事件系统

### 框架核心理念
框架提供三种**对等的、可互相嵌套的元能力原语**：

1. **Skills**（知识性能力）：可发现、可注入的指导性原则和行为规范
   - 作为知识注入到 Agent 的 context
   - 携带调度规则，指导何时调用哪个 Agent 或 Workflow

2. **Agent**（智能性能力）：具有自主决策能力的执行体
   - 通过 Skills 定义自身能力
   - 与其他 Agent 协作
   - 调用 Workflow 作为原子能力

3. **Workflow**（结构性能力）：确定性的、可重复的编排流程
   - 编排 Agent 作为步骤
   - 包含循环、并行、条件分支
   - 作为原子能力被 Agent 或其他 Workflow 调用

**三者不是层级关系，而是对等的，可互相嵌套：**
```
Skills → 可调度 Agent 和 Workflow
Agent → 可装载 Skills，可调用 Workflow，可与其他 Agent 协作
Workflow → 可编排 Agent，可嵌套其他 Workflow
```

### 框架的边界（极其重要）
**框架只做三件事：让能力可以被声明、被执行、被组合。**

框架**不关心**：
- 执行结果要不要给人看（业务决定）
- 人看完要不要修改（业务决定）
- 修改完再不再执行下一步（业务决定）
- 任何人机交互的定义和编排（业务决定）

框架的职责是：接收输入 → 执行能力 → 返回结果。业务层拿到结果后自行决定后续流程。

### 框架原则（必须遵守）
- **不侵入上游**：不 fork Agently 和 skills-runtime-sdk，只通过公共 API 桥接
- **随上游进化**：适配器层可随上游 API 变化更新
- **通用不绑业务**：不包含任何特定业务逻辑，不预设使用场景
- **轻量灵活**：概念最少化
- **能力收敛**：业务层只需面对本框架，不需直接接触上游

---

## 二、仓库现状与处置决策（必读）

### 当前仓库结构
```
agently-skills-runtime/
├── src/agently_skills_runtime/
│   ├── __init__.py
│   ├── runtime.py              # AgentlySkillsRuntime — 旧主入口
│   ├── types.py                # NodeReportV2, NodeResultV2
│   ├── config.py               # BridgeConfigModel
│   ├── adapters/
│   │   ├── agently_backend.py  # AgentlyChatBackend — LLM 传输适配
│   │   └── triggerflow_tool.py # TriggerFlow tool
│   └── reporting/
│       └── node_report.py      # NodeReportBuilder
├── tests/
├── config/
├── projects/agently-skills-web-prototype/
└── pyproject.toml
```

### 处置决策

**保留并迁移：**
1. `adapters/agently_backend.py` → 迁移为 `adapters/llm_backend.py`
   - AgentlyChatBackend、AgentlyRequester 协议、build_openai_compatible_requester_factory
   - 设计良好的传输层桥接，直接复用

2. `reporting/node_report.py` 的事件聚合理念 → 参考迁移到 `reporting/builder.py`

**推倒重来：**
1. `runtime.py` → 重写为 `runtime/engine.py`（从"单次 run 包装器"→"能力注册+组合+执行引擎"）
2. `types.py` → 替换为 `protocol/` 下的类型定义
3. `adapters/triggerflow_tool.py` → 重新设计为 WorkflowAdapter 的可选引擎
4. `__init__.py` → 全部重写

---

## 三、目标架构与完整规格

### 新包结构

```
agently-skills-runtime/
├── src/agently_skills_runtime/
│   ├── __init__.py                     # 公共 API 导出
│   │
│   ├── protocol/                       # 能力协议（纯类型定义，不依赖上游）
│   │   ├── __init__.py
│   │   ├── capability.py               # CapabilitySpec, CapabilityKind, CapabilityRef, CapabilityResult, CapabilityStatus
│   │   ├── skill.py                    # SkillSpec, SkillDispatchRule
│   │   ├── agent.py                    # AgentSpec, AgentIOSchema
│   │   ├── workflow.py                 # WorkflowSpec, Step, LoopStep, ParallelStep, ConditionalStep, InputMapping
│   │   └── context.py                  # ExecutionContext, RecursionLimitError
│   │
│   ├── runtime/                        # 能力运行时（执行引擎）
│   │   ├── __init__.py
│   │   ├── engine.py                   # CapabilityRuntime（主入口）, RuntimeConfig
│   │   ├── registry.py                 # CapabilityRegistry
│   │   ├── loop.py                     # LoopController
│   │   └── guards.py                   # ExecutionGuards, LoopBreakerError
│   │
│   ├── adapters/                       # 上游适配器
│   │   ├── __init__.py
│   │   ├── skill_adapter.py            # SkillAdapter
│   │   ├── agent_adapter.py            # AgentAdapter
│   │   ├── workflow_adapter.py         # WorkflowAdapter
│   │   ├── llm_backend.py             # AgentlyChatBackend（从旧代码迁移）
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
│   │   ├── test_capability.py
│   │   ├── test_context.py
│   │   └── test_workflow.py
│   ├── runtime/
│   │   ├── test_registry.py
│   │   ├── test_engine.py
│   │   ├── test_loop.py
│   │   └── test_guards.py
│   ├── adapters/
│   │   ├── test_skill_adapter.py
│   │   ├── test_agent_adapter.py
│   │   └── test_workflow_adapter.py
│   └── scenarios/
│       └── test_workflow_with_loop.py
│
├── config/
│   └── default.yaml
├── pyproject.toml
└── README.md
```

---

### 各模块详细规格

#### protocol/capability.py — 统一能力接口

```python
"""三种元能力共享的统一接口。"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime


class CapabilityKind(str, Enum):
    SKILL = "skill"
    AGENT = "agent"
    WORKFLOW = "workflow"


@dataclass(frozen=True)
class CapabilityRef:
    """能力引用——在组合中引用另一个能力。"""
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

---

#### protocol/skill.py — Skills 声明

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
    dispatch_rules: 使 Skills 具备主动调度能力
    inject_to: 声明自动注入到哪些 Agent
    """
    base: CapabilitySpec
    source: str
    source_type: str = "file"
    dispatch_rules: List[SkillDispatchRule] = field(default_factory=list)
    inject_to: List[str] = field(default_factory=list)
```

---

#### protocol/agent.py — Agent 声明

```python
"""Agent 元能力声明。"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from .capability import CapabilitySpec, CapabilityRef


@dataclass(frozen=True)
class AgentIOSchema:
    """轻量 IO schema。"""
    fields: Dict[str, str] = field(default_factory=dict)    # {"synopsis": "str"}
    required: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentSpec:
    """
    Agent 声明。
    skills: 装载的 Skill ID 列表
    collaborators: 可协作的其他 Agent
    callable_workflows: 可调用的 Workflow
    loop_compatible: 是否可被循环调用
    llm_config: LLM 覆盖配置（不设则继承全局）
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

---

#### protocol/workflow.py — Workflow 声明

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

---

#### protocol/context.py — 执行上下文

```python
"""执行上下文——跨能力状态传递和调用链管理。"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class RecursionLimitError(Exception):
    """嵌套深度超限。"""
    pass


@dataclass
class ExecutionContext:
    """
    执行上下文。
    职责：追踪调用链、管理递归深度、传递共享数据、记录步骤输出。
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
                f"Depth {self.depth + 1} > max {self.max_depth}. Chain: {self.call_chain + [capability_id]}"
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

---

#### runtime/registry.py — 能力注册表

```python
"""能力注册表——注册、发现、依赖校验。"""

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
    - register(spec): 注册，重复 ID 覆盖
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

---

#### runtime/engine.py — 主入口

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

# RuntimeConfig:
# - workspace_root: str = "."
# - sdk_config_paths: List[str] = []
# - agently_agent: Any = None          # 宿主提供的 Agently agent 实例
# - preflight_mode: str = "error"      # error | warn | off
# - max_loop_iterations: int = 200     # 全局循环上限
# - max_depth: int = 10                # 全局嵌套深度上限
```

---

#### runtime/loop.py — 循环控制

```python
"""循环控制器。"""

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

---

#### runtime/guards.py — 执行守卫

```python
"""递归深度、循环熔断。"""

# ExecutionGuards:
# - max_total_loop_iterations: int = 5000
# - record_loop_iteration(): 超限抛 LoopBreakerError
#
# class LoopBreakerError(Exception): pass
```

---

#### adapters/llm_backend.py — LLM 传输（从现有代码迁移）

从现有 `adapters/agently_backend.py` 直接迁移，保持所有功能不变：
- AgentlyChatBackend（实现 SDK ChatBackend 接口）
- AgentlyRequester / AgentlyRequesterFactory 协议
- build_openai_compatible_requester_factory 函数

文件重命名为 `llm_backend.py`，更新 import 路径。

---

#### adapters/skill_adapter.py

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

---

#### adapters/agent_adapter.py

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

---

#### adapters/workflow_adapter.py

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

---

#### __init__.py — 公共导出

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

---

### pyproject.toml

```toml
[project]
name = "agently-skills-runtime"
version = "0.2.0"
description = "Capability-oriented AI agent framework bridging Agently and Skills Runtime SDK."
requires-python = ">=3.10"
dependencies = [
  "agently",
  "skills-runtime-sdk-python",
  "PyYAML",
]

[project.optional-dependencies]
dev = ["pytest>=7", "pytest-asyncio>=0.23"]

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
addopts = "-q"
asyncio_mode = "auto"
testpaths = ["tests"]
```

---

## 四、实施步骤

严格按顺序：

### Step 1: 创建 protocol/
实现 5 个文件：capability.py, skill.py, agent.py, workflow.py, context.py。
纯 dataclass/enum，不依赖上游。

### Step 2: 创建 runtime/
- registry.py（注册表 + 依赖校验）
- guards.py（执行守卫）
- loop.py（循环控制器）
- engine.py（主入口，分发逻辑）

### Step 3: 创建 adapters/
- 迁移 llm_backend.py（从现有 agently_backend.py 复制并更新 import）
- 实现 skill_adapter.py
- 实现 agent_adapter.py
- 实现 workflow_adapter.py

### Step 4: 更新入口
- 重写 __init__.py
- 更新 pyproject.toml
- 创建 errors.py

### Step 5: 编写测试
- tests/protocol/test_context.py：resolve_mapping 所有 6 种前缀、child() 递归限制
- tests/protocol/test_capability.py：CapabilitySpec 构造、CapabilityResult 字段
- tests/runtime/test_registry.py：注册、查找、validate_dependencies（含缺失依赖检测）
- tests/runtime/test_loop.py：正常循环、max_iterations 超限、迭代失败中止
- tests/runtime/test_guards.py：LoopBreakerError
- tests/runtime/test_engine.py：mock adapter 测试分发逻辑
- tests/scenarios/test_workflow_with_loop.py：Workflow 编排 2 个 Agent + 循环（mock LLM）

### Step 6: 清理
- 删除旧 runtime.py、types.py
- 旧 projects/agently-skills-web-prototype/ 保留不动
- 更新 README.md

---

## 五、关键约束

1. **Python 3.10+**，使用 `from __future__ import annotations`
2. **protocol/ 纯 dataclass**，不用 Pydantic（保持零依赖轻量）
3. **所有 Adapter.execute() 必须 async**
4. **不 import 上游私有 API**——只通过公共接口桥接
5. **ExecutionContext.child() 必须检查 max_depth**——防无限递归的核心守卫
6. **LoopController 双重限制**：步骤级 max_iterations + 全局 max_total_loop_iterations
7. **框架不包含任何业务逻辑**——不出现特定业务词汇
8. **框架不定义人机交互**——不出现 HumanInteraction、approve、review 等概念；是否需要人参与是业务层的决策
9. **保留 projects/agently-skills-web-prototype/ 不删除**

---

## 六、验收标准

1. `pip install -e .` 成功
2. `python -c "from agently_skills_runtime import CapabilityRuntime, SkillSpec, AgentSpec, WorkflowSpec"` 无报错
3. `pytest tests/protocol/` 全部通过
4. `pytest tests/runtime/` 全部通过
5. 至少一个 scenario 测试通过：Workflow 编排 2 Agent + LoopStep（mock LLM）
6. `CapabilityRegistry.validate_dependencies()` 能检测缺失依赖
7. `ExecutionContext.child()` 超 max_depth 抛 RecursionLimitError
8. `ExecutionContext.resolve_mapping()` 正确处理所有 6 种前缀

---

## 七、使用示例（验收参考）

```python
from agently_skills_runtime import (
    CapabilityRuntime, RuntimeConfig,
    CapabilitySpec, CapabilityKind, CapabilityRef,
    SkillSpec, AgentSpec, WorkflowSpec,
    Step, LoopStep, InputMapping,
)

config = RuntimeConfig(workspace_root=".", agently_agent=my_agent)
runtime = CapabilityRuntime(config=config)

# 注册
runtime.register(SkillSpec(
    base=CapabilitySpec(id="skill-guide", kind=CapabilityKind.SKILL, name="Guide"),
    source="skills/guide.md",
))
runtime.register(AgentSpec(
    base=CapabilitySpec(id="agent-planner", kind=CapabilityKind.AGENT, name="Planner"),
    skills=["skill-guide"],
))
runtime.register(AgentSpec(
    base=CapabilitySpec(id="agent-worker", kind=CapabilityKind.AGENT, name="Worker"),
    skills=["skill-guide"],
    loop_compatible=True,
))
runtime.register(WorkflowSpec(
    base=CapabilitySpec(id="wf-main", kind=CapabilityKind.WORKFLOW, name="Main"),
    steps=[
        Step(id="plan", capability=CapabilityRef(id="agent-planner"),
             input_mappings=[InputMapping(source="context.task", target_field="task")]),
        LoopStep(id="work", capability=CapabilityRef(id="agent-worker"),
                 iterate_over="step.plan.items",
                 item_input_mappings=[InputMapping(source="item", target_field="item")],
                 max_iterations=50, collect_as="results"),
    ],
))

# 校验 + 执行
runtime.validate()
result = await runtime.run("wf-main", context_bag={"task": "do something"})
# result.status == CapabilityStatus.SUCCESS
# result.output == {"results": [...]}
```
