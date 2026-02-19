# Codex 指令 — Phase 1：Protocol 层 + 基础设施

> 本阶段目标：建立 Protocol 层（纯类型定义）+ 重命名 bridge + 更新导出 + Protocol 全量测试。
> 预计产出：13 个新文件 + 2 个修改文件。
> 约束：Protocol 层不 import 任何上游模块（agently / agent_sdk）。

---

## 背景信息

### 你正在操作的仓库

`agently-skills-runtime` — 一个桥接胶水层框架，桥接上游 Agently（LLM 传输 + TriggerFlow）和 skills-runtime-sdk（Agent 引擎 + ToolRegistry + WAL）。

### 当前仓库结构（v0.3.0）

```
src/agently_skills_runtime/
├── __init__.py
├── runtime.py          ← 桥接层主入口（即将重命名为 bridge.py）
├── types.py            ← NodeReportV2/NodeResultV2
├── config.py           ← BridgeConfigModel
├── adapters/
│   ├── __init__.py
│   ├── agently_backend.py    ← AgentlyChatBackend（已有 ✅）
│   ├── triggerflow_tool.py   ← TriggerFlowTool（已有 ✅）
│   └── upstream.py           ← 上游 fork 校验（已有 ✅）
└── reporting/
    ├── __init__.py
    └── node_report.py        ← NodeReportBuilder（已有 ✅）
```

### 不可违反的约束

1. **不修改已有的 adapters/agently_backend.py、adapters/triggerflow_tool.py、adapters/upstream.py、reporting/node_report.py、types.py、config.py 的内容**
2. **Protocol 层（`protocol/` 目录下）不得 import agently 或 agent_sdk**
3. **所有文件必须以 `from __future__ import annotations` 开头**
4. **Python >= 3.10**
5. **已有的 pytest 测试必须继续通过**

---

## Step 1：重命名 runtime.py → bridge.py

### 操作

```bash
cd src/agently_skills_runtime
git mv runtime.py bridge.py
```

### 目的
为新增的 `runtime/` 目录让出路径。`bridge.py` 更准确地表达该模块的角色（桥接层主入口）。

### 验证
重命名后，`bridge.py` 的内容不变，只是文件名变了。

---

## Step 2：创建 protocol/ 目录及 5 个文件

### 2.1 创建 `src/agently_skills_runtime/protocol/__init__.py`

```python
"""Protocol 层：纯能力类型定义，不依赖任何上游模块。"""
from __future__ import annotations

from .capability import (
    CapabilityKind,
    CapabilityRef,
    CapabilitySpec,
    CapabilityStatus,
    CapabilityResult,
)
from .skill import SkillSpec, SkillDispatchRule
from .agent import AgentSpec, AgentIOSchema
from .workflow import (
    WorkflowSpec,
    Step,
    LoopStep,
    ParallelStep,
    ConditionalStep,
    InputMapping,
    WorkflowStep,
)
from .context import ExecutionContext, RecursionLimitError

__all__ = [
    "CapabilityKind",
    "CapabilityRef",
    "CapabilitySpec",
    "CapabilityStatus",
    "CapabilityResult",
    "SkillSpec",
    "SkillDispatchRule",
    "AgentSpec",
    "AgentIOSchema",
    "WorkflowSpec",
    "Step",
    "LoopStep",
    "ParallelStep",
    "ConditionalStep",
    "InputMapping",
    "WorkflowStep",
    "ExecutionContext",
    "RecursionLimitError",
]
```

### 2.2 创建 `src/agently_skills_runtime/protocol/capability.py`

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
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class CapabilityResult:
    """
    所有能力执行后返回此结构。

    参数：
    - status: 执行状态
    - output: 执行输出（类型由具体能力决定，通常是 dict 或 str）
    - error: 错误信息（仅 FAILED 时非 None）
    - report: 执行报告（可选，通常是 NodeReport 或嵌套的子报告列表）
    - artifacts: 产出的文件路径列表
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

### 2.3 创建 `src/agently_skills_runtime/protocol/skill.py`

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

    参数：
    - condition: 触发条件表达式（Phase 1 支持简单的 context bag key 存在性检查）
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
    """
    base: CapabilitySpec
    source: str
    source_type: str = "file"
    dispatch_rules: List[SkillDispatchRule] = field(default_factory=list)
    inject_to: List[str] = field(default_factory=list)
```

### 2.4 创建 `src/agently_skills_runtime/protocol/agent.py`

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
    - skills: 装载的 Skill ID 列表
    - tools: 注册的 Tool 名称列表
    - collaborators: 可协作的其他 Agent 引用
    - callable_workflows: 可调用的 Workflow 引用
    - input_schema: 输入 schema（可选）
    - output_schema: 输出 schema（可选）
    - loop_compatible: 是否可被 LoopStep 循环调用
    - llm_config: LLM 覆盖配置
    - prompt_template: 可选的 prompt 模板（支持 {field} 占位符）
    - system_prompt: 可选的 system prompt
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

### 2.5 创建 `src/agently_skills_runtime/protocol/workflow.py`

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

    source 支持 6 种前缀：
    - "context.{key}" → 从 ExecutionContext.bag 读取
    - "previous.{key}" → 从上一步输出读取
    - "step.{step_id}.{key}" → 从指定步骤输出读取
    - "step.{step_id}" → 指定步骤输出整体
    - "literal.{value}" → 字面量字符串
    - "item" / "item.{key}" → 循环中当前元素

    参数：
    - source: 数据源表达式
    - target_field: 目标输入字段名
    """
    source: str
    target_field: str


@dataclass(frozen=True)
class Step:
    """
    基础步骤——执行单个能力。

    参数：
    - id: 步骤 ID（在 Workflow 内唯一）
    - capability: 要调用的能力引用
    - input_mappings: 输入映射列表
    """
    id: str
    capability: CapabilityRef
    input_mappings: List[InputMapping] = field(default_factory=list)


@dataclass(frozen=True)
class LoopStep:
    """
    循环步骤——对集合中每个元素执行能力。

    业务场景：
    - MA-006 对每个候选选题评分
    - MA-013 对每个角色设计小传
    - MA-021 对每个章节扩写
    - MA-024 对每集编写剧本
    - MA-026/027 对每个镜头生成分镜/Prompt

    参数：
    - id: 步骤 ID
    - capability: 每次循环调用的能力引用
    - iterate_over: 数据源表达式（解析后应为 List）
    - item_input_mappings: 循环内的输入映射（可用 "item"/"item.{key}" 前缀）
    - max_iterations: 单步最大循环次数
    - collect_as: 结果收集字段名
    - fail_strategy: "abort" | "skip" | "collect"
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

    业务场景：WF-001A 中 MA-001/002/003 并行执行市场分析。

    参数：
    - id: 步骤 ID
    - branches: 并行执行的步骤列表
    - join_strategy: "all_success" | "any_success" | "best_effort"
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
    - condition_source: 条件值的数据源表达式
    - branches: 条件值 → 步骤的映射
    - default: 无匹配时的默认步骤
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
    - steps: 步骤列表（按声明顺序执行，ParallelStep 内部并行）
    - context_schema: 初始 context bag 的 schema（可选）
    - output_mappings: 输出映射（从 context/step_outputs 构造最终输出）
    """
    base: CapabilitySpec
    steps: List[WorkflowStep] = field(default_factory=list)
    context_schema: Optional[Dict[str, str]] = None
    output_mappings: List[InputMapping] = field(default_factory=list)
```

### 2.6 创建 `src/agently_skills_runtime/protocol/context.py`

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

    每次 Engine._execute() 调用时，创建 child context（depth+1），
    确保嵌套调用有独立的 step_outputs 空间，同时共享 bag 数据（浅拷贝）。

    参数：
    - run_id: 顶层运行 ID
    - parent_context: 父上下文（用于追溯调用链）
    - depth: 当前嵌套深度（从 0 开始）
    - max_depth: 最大嵌套深度
    - bag: 全局数据袋（浅拷贝传递）
    - step_outputs: 当前层级的步骤输出缓存（step_id → output）
    - call_chain: 调用链记录（能力 ID 列表）
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
        - depth + 1；超过 max_depth 抛 RecursionLimitError
        - bag 浅拷贝（子 context 可修改自己的 bag 而不影响父级）
        - step_outputs 清空（子 context 有独立的步骤输出空间）
        - call_chain 追加当前 capability_id
        """
        new_depth = self.depth + 1
        if new_depth > self.max_depth:
            raise RecursionLimitError(
                f"Recursion depth {new_depth} exceeds max {self.max_depth}. "
                f"Call chain: {self.call_chain + [capability_id]}"
            )
        return ExecutionContext(
            run_id=self.run_id,
            parent_context=self,
            depth=new_depth,
            max_depth=self.max_depth,
            bag=dict(self.bag),
            step_outputs={},
            call_chain=self.call_chain + [capability_id],
        )

    def resolve_mapping(self, expression: str) -> Any:
        """
        解析映射表达式，从 context 中提取数据。

        支持 6 种前缀：
        - "context.{key}" → self.bag[key]
        - "previous.{key}" → 最后一个 step_output 的 [key]
        - "step.{step_id}.{key}" → self.step_outputs[step_id][key]
        - "step.{step_id}" → self.step_outputs[step_id]（整体）
        - "literal.{value}" → 字面量字符串
        - "item" → self.bag["__current_item__"]
        - "item.{key}" → self.bag["__current_item__"][key]

        找不到时返回 None（不抛异常）。
        """
        if expression.startswith("context."):
            key = expression[len("context."):]
            return self.bag.get(key)

        if expression.startswith("previous."):
            key = expression[len("previous."):]
            if not self.step_outputs:
                return None
            last_key = list(self.step_outputs.keys())[-1]
            last_out = self.step_outputs[last_key]
            if isinstance(last_out, dict):
                return last_out.get(key)
            return None

        if expression.startswith("step."):
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

        if expression.startswith("literal."):
            return expression[len("literal."):]

        if expression == "item":
            return self.bag.get("__current_item__")

        if expression.startswith("item."):
            key = expression[len("item."):]
            item = self.bag.get("__current_item__")
            if isinstance(item, dict):
                return item.get(key)
            return None

        return None
```

---

## Step 3：创建 errors.py

创建 `src/agently_skills_runtime/errors.py`：

```python
"""框架统一错误定义。"""
from __future__ import annotations

from .protocol.context import RecursionLimitError  # re-export


class AgentlySkillsRuntimeError(Exception):
    """框架基础错误。"""
    pass


class AdapterNotFoundError(AgentlySkillsRuntimeError):
    """指定类型没有注册 Adapter。"""
    pass


class CapabilityNotFoundError(AgentlySkillsRuntimeError):
    """指定 ID 的能力未注册。"""
    pass


__all__ = [
    "AgentlySkillsRuntimeError",
    "AdapterNotFoundError",
    "CapabilityNotFoundError",
    "RecursionLimitError",
]
```

---

## Step 4：更新 `__init__.py`

更新 `src/agently_skills_runtime/__init__.py`，同时保持已有导出不变：

```python
"""agently-skills-runtime: 桥接胶水层 + 能力组织层。"""
from __future__ import annotations

# === 桥接层导出（保持向后兼容）===
from .bridge import AgentlySkillsRuntime, AgentlySkillsRuntimeConfig  # 原 runtime.py
from .types import NodeReportV2, NodeResultV2
from .config import BridgeConfigModel

# === Protocol 导出 ===
from .protocol.capability import (
    CapabilityKind,
    CapabilityRef,
    CapabilitySpec,
    CapabilityStatus,
    CapabilityResult,
)
from .protocol.skill import SkillSpec, SkillDispatchRule
from .protocol.agent import AgentSpec, AgentIOSchema
from .protocol.workflow import (
    WorkflowSpec,
    Step,
    LoopStep,
    ParallelStep,
    ConditionalStep,
    InputMapping,
    WorkflowStep,
)
from .protocol.context import ExecutionContext, RecursionLimitError

# === 错误导出 ===
from .errors import (
    AgentlySkillsRuntimeError,
    AdapterNotFoundError,
    CapabilityNotFoundError,
)

__all__ = [
    # Bridge
    "AgentlySkillsRuntime",
    "AgentlySkillsRuntimeConfig",
    "NodeReportV2",
    "NodeResultV2",
    "BridgeConfigModel",
    # Protocol
    "CapabilityKind",
    "CapabilityRef",
    "CapabilitySpec",
    "CapabilityStatus",
    "CapabilityResult",
    "SkillSpec",
    "SkillDispatchRule",
    "AgentSpec",
    "AgentIOSchema",
    "WorkflowSpec",
    "Step",
    "LoopStep",
    "ParallelStep",
    "ConditionalStep",
    "InputMapping",
    "WorkflowStep",
    "ExecutionContext",
    "RecursionLimitError",
    # Errors
    "AgentlySkillsRuntimeError",
    "AdapterNotFoundError",
    "CapabilityNotFoundError",
]
```

**关键**：注意 `from .bridge import ...` 而不是 `from .runtime import ...`。

---

## Step 5：修复已有测试中对 runtime 的 import

搜索所有测试文件中 `import agently_skills_runtime.runtime` 或 `from agently_skills_runtime.runtime import` 的引用，替换为 `agently_skills_runtime.bridge`。

```bash
# 搜索需要修改的文件
grep -r "agently_skills_runtime.runtime" tests/ --include="*.py" -l
grep -r "agently_skills_runtime\.runtime" tests/ --include="*.py" -l
```

对每个找到的文件，将 `agently_skills_runtime.runtime` 替换为 `agently_skills_runtime.bridge`。

例如，如果 `tests/test_runtime_hooks_and_schema_gate.py` 存在：
```python
# 旧
import agently_skills_runtime.runtime as runtime_mod
# 新
import agently_skills_runtime.bridge as runtime_mod
```

**同时**检查 `bridge.py` 内部是否有自引用（如 `from agently_skills_runtime.runtime import ...`），也需要修改。

---

## Step 6：创建 Protocol 测试

### 6.1 创建 `tests/protocol/` 目录

```bash
mkdir -p tests/protocol
touch tests/protocol/__init__.py
```

### 6.2 创建 `tests/protocol/test_capability.py`

```python
"""CapabilitySpec / CapabilityResult 单元测试。"""
from __future__ import annotations

from agently_skills_runtime.protocol.capability import (
    CapabilityKind,
    CapabilityRef,
    CapabilitySpec,
    CapabilityStatus,
    CapabilityResult,
)


def test_capability_kind_values():
    assert CapabilityKind.SKILL == "skill"
    assert CapabilityKind.AGENT == "agent"
    assert CapabilityKind.WORKFLOW == "workflow"


def test_capability_spec_construction():
    spec = CapabilitySpec(
        id="MA-013",
        kind=CapabilityKind.AGENT,
        name="单角色设计师",
        description="设计单个角色",
        version="1.0.0",
        tags=["TP2", "人物"],
        metadata={"author": "test"},
    )
    assert spec.id == "MA-013"
    assert spec.kind == CapabilityKind.AGENT
    assert spec.name == "单角色设计师"
    assert spec.version == "1.0.0"
    assert "TP2" in spec.tags
    assert spec.metadata["author"] == "test"


def test_capability_spec_defaults():
    spec = CapabilitySpec(id="x", kind=CapabilityKind.SKILL, name="x")
    assert spec.description == ""
    assert spec.version == "0.1.0"
    assert spec.tags == []
    assert spec.metadata == {}


def test_capability_ref():
    ref = CapabilityRef(id="MA-013", kind=CapabilityKind.AGENT)
    assert ref.id == "MA-013"
    assert ref.kind == CapabilityKind.AGENT

    ref_no_kind = CapabilityRef(id="WF-001")
    assert ref_no_kind.kind is None


def test_capability_status_values():
    assert CapabilityStatus.PENDING == "pending"
    assert CapabilityStatus.SUCCESS == "success"
    assert CapabilityStatus.FAILED == "failed"


def test_capability_result_success():
    r = CapabilityResult(
        status=CapabilityStatus.SUCCESS,
        output={"score": 85},
        duration_ms=1234.5,
    )
    assert r.status == CapabilityStatus.SUCCESS
    assert r.output["score"] == 85
    assert r.error is None
    assert r.artifacts == []
    assert r.duration_ms == 1234.5


def test_capability_result_failed():
    r = CapabilityResult(
        status=CapabilityStatus.FAILED,
        error="timeout",
        metadata={"retry_count": 3},
    )
    assert r.status == CapabilityStatus.FAILED
    assert r.error == "timeout"
    assert r.metadata["retry_count"] == 3
```

### 6.3 创建 `tests/protocol/test_skill.py`

```python
"""SkillSpec 单元测试。"""
from __future__ import annotations

from agently_skills_runtime.protocol.capability import CapabilitySpec, CapabilityKind, CapabilityRef
from agently_skills_runtime.protocol.skill import SkillSpec, SkillDispatchRule


def test_skill_spec_file():
    spec = SkillSpec(
        base=CapabilitySpec(id="story-tpl", kind=CapabilityKind.SKILL, name="故事模板"),
        source="skills/story-template/SKILL.md",
        source_type="file",
    )
    assert spec.base.id == "story-tpl"
    assert spec.source_type == "file"
    assert spec.dispatch_rules == []
    assert spec.inject_to == []


def test_skill_spec_inline():
    spec = SkillSpec(
        base=CapabilitySpec(id="inline-s", kind=CapabilityKind.SKILL, name="内联"),
        source="这是 Skill 内容文本",
        source_type="inline",
    )
    assert spec.source_type == "inline"
    assert "Skill 内容" in spec.source


def test_skill_dispatch_rule():
    rule = SkillDispatchRule(
        condition="low_score",
        target=CapabilityRef(id="MA-007"),
        priority=10,
    )
    assert rule.condition == "low_score"
    assert rule.target.id == "MA-007"
    assert rule.priority == 10


def test_skill_inject_to():
    spec = SkillSpec(
        base=CapabilitySpec(id="char-tpl", kind=CapabilityKind.SKILL, name="角色模板"),
        source="inline content",
        source_type="inline",
        inject_to=["MA-013", "MA-014"],
    )
    assert "MA-013" in spec.inject_to
    assert "MA-014" in spec.inject_to
```

### 6.4 创建 `tests/protocol/test_agent.py`

```python
"""AgentSpec 单元测试。"""
from __future__ import annotations

from agently_skills_runtime.protocol.capability import CapabilitySpec, CapabilityKind, CapabilityRef
from agently_skills_runtime.protocol.agent import AgentSpec, AgentIOSchema


def test_agent_spec_minimal():
    spec = AgentSpec(
        base=CapabilitySpec(id="MA-013", kind=CapabilityKind.AGENT, name="单角色设计师"),
    )
    assert spec.base.id == "MA-013"
    assert spec.skills == []
    assert spec.tools == []
    assert spec.loop_compatible is False
    assert spec.llm_config is None
    assert spec.prompt_template is None
    assert spec.system_prompt is None


def test_agent_spec_full():
    spec = AgentSpec(
        base=CapabilitySpec(
            id="MA-013",
            kind=CapabilityKind.AGENT,
            name="单角色设计师",
            tags=["TP2"],
        ),
        skills=["story-tpl", "char-tpl"],
        tools=["web_search"],
        collaborators=[CapabilityRef(id="MA-014")],
        callable_workflows=[CapabilityRef(id="WF-001D")],
        input_schema=AgentIOSchema(
            fields={"角色定位": "str", "故事梗概": "str"},
            required=["角色定位"],
        ),
        output_schema=AgentIOSchema(fields={"角色小传": "str"}),
        loop_compatible=True,
        llm_config={"model": "deepseek-chat", "temperature": 0.7},
        prompt_template="设计角色：{角色定位}",
        system_prompt="你是角色设计专家",
    )
    assert len(spec.skills) == 2
    assert spec.loop_compatible is True
    assert spec.input_schema.required == ["角色定位"]
    assert spec.llm_config["model"] == "deepseek-chat"


def test_agent_io_schema_defaults():
    schema = AgentIOSchema()
    assert schema.fields == {}
    assert schema.required == []
```

### 6.5 创建 `tests/protocol/test_workflow.py`

```python
"""WorkflowSpec 单元测试。"""
from __future__ import annotations

from agently_skills_runtime.protocol.capability import CapabilitySpec, CapabilityKind, CapabilityRef
from agently_skills_runtime.protocol.workflow import (
    WorkflowSpec, Step, LoopStep, ParallelStep, ConditionalStep, InputMapping,
)


def test_step_construction():
    step = Step(
        id="s1",
        capability=CapabilityRef(id="MA-013A"),
        input_mappings=[InputMapping(source="context.故事梗概", target_field="故事梗概")],
    )
    assert step.id == "s1"
    assert step.capability.id == "MA-013A"
    assert len(step.input_mappings) == 1


def test_loop_step_construction():
    step = LoopStep(
        id="s2",
        capability=CapabilityRef(id="MA-013"),
        iterate_over="step.s1.角色列表",
        item_input_mappings=[InputMapping(source="item.定位", target_field="角色定位")],
        max_iterations=20,
        fail_strategy="skip",
    )
    assert step.iterate_over == "step.s1.角色列表"
    assert step.max_iterations == 20
    assert step.fail_strategy == "skip"


def test_parallel_step_construction():
    step = ParallelStep(
        id="p1",
        branches=[
            Step(id="b1", capability=CapabilityRef(id="MA-001")),
            Step(id="b2", capability=CapabilityRef(id="MA-002")),
            Step(id="b3", capability=CapabilityRef(id="MA-003")),
        ],
        join_strategy="all_success",
    )
    assert len(step.branches) == 3
    assert step.join_strategy == "all_success"


def test_conditional_step_construction():
    step = ConditionalStep(
        id="c1",
        condition_source="step.classify.category",
        branches={
            "romance": Step(id="br1", capability=CapabilityRef(id="MA-010")),
            "action": Step(id="br2", capability=CapabilityRef(id="MA-011")),
        },
        default=Step(id="default", capability=CapabilityRef(id="MA-012")),
    )
    assert len(step.branches) == 2
    assert step.default is not None


def test_workflow_spec_full():
    wf = WorkflowSpec(
        base=CapabilitySpec(
            id="WF-001D",
            kind=CapabilityKind.WORKFLOW,
            name="人物塑造子流程",
        ),
        steps=[
            Step(id="s1", capability=CapabilityRef(id="MA-013A")),
            LoopStep(
                id="s2",
                capability=CapabilityRef(id="MA-013"),
                iterate_over="step.s1.角色列表",
                max_iterations=20,
            ),
            Step(id="s3", capability=CapabilityRef(id="MA-014")),
            LoopStep(
                id="s4",
                capability=CapabilityRef(id="MA-015"),
                iterate_over="step.s2",
                max_iterations=20,
            ),
        ],
        output_mappings=[
            InputMapping(source="step.s2", target_field="角色小传列表"),
            InputMapping(source="step.s3", target_field="关系图谱"),
        ],
    )
    assert len(wf.steps) == 4
    assert len(wf.output_mappings) == 2
```

### 6.6 创建 `tests/protocol/test_context.py`

```python
"""ExecutionContext 单元测试。"""
from __future__ import annotations

import pytest

from agently_skills_runtime.protocol.context import ExecutionContext, RecursionLimitError


class TestResolveMapping:
    """resolve_mapping 6 种前缀全覆盖。"""

    def test_context_prefix(self):
        ctx = ExecutionContext(run_id="r1", bag={"name": "Alice", "age": 25})
        assert ctx.resolve_mapping("context.name") == "Alice"
        assert ctx.resolve_mapping("context.age") == 25
        assert ctx.resolve_mapping("context.missing") is None

    def test_previous_prefix(self):
        ctx = ExecutionContext(run_id="r1")
        ctx.step_outputs["s1"] = {"score": 80}
        ctx.step_outputs["s2"] = {"grade": "A"}
        # previous 指最后一个 step_output
        assert ctx.resolve_mapping("previous.grade") == "A"
        assert ctx.resolve_mapping("previous.missing") is None

    def test_previous_no_outputs(self):
        ctx = ExecutionContext(run_id="r1")
        assert ctx.resolve_mapping("previous.anything") is None

    def test_step_prefix_with_key(self):
        ctx = ExecutionContext(run_id="r1")
        ctx.step_outputs["plan"] = {"角色列表": ["A", "B", "C"]}
        assert ctx.resolve_mapping("step.plan.角色列表") == ["A", "B", "C"]
        assert ctx.resolve_mapping("step.plan.missing") is None
        assert ctx.resolve_mapping("step.nonexistent.key") is None

    def test_step_prefix_whole_output(self):
        ctx = ExecutionContext(run_id="r1")
        ctx.step_outputs["s1"] = {"x": 1, "y": 2}
        result = ctx.resolve_mapping("step.s1")
        assert result == {"x": 1, "y": 2}

    def test_literal_prefix(self):
        ctx = ExecutionContext(run_id="r1")
        assert ctx.resolve_mapping("literal.hello world") == "hello world"
        assert ctx.resolve_mapping("literal.") == ""

    def test_item_prefix(self):
        ctx = ExecutionContext(
            run_id="r1",
            bag={"__current_item__": {"name": "角色A", "type": "主角"}},
        )
        assert ctx.resolve_mapping("item") == {"name": "角色A", "type": "主角"}
        assert ctx.resolve_mapping("item.name") == "角色A"
        assert ctx.resolve_mapping("item.type") == "主角"
        assert ctx.resolve_mapping("item.missing") is None

    def test_item_no_current_item(self):
        ctx = ExecutionContext(run_id="r1")
        assert ctx.resolve_mapping("item") is None
        assert ctx.resolve_mapping("item.name") is None

    def test_unknown_prefix_returns_none(self):
        ctx = ExecutionContext(run_id="r1")
        assert ctx.resolve_mapping("unknown.key") is None
        assert ctx.resolve_mapping("") is None


class TestChild:
    """child() 递归深度控制。"""

    def test_child_increments_depth(self):
        parent = ExecutionContext(run_id="r1", depth=0, max_depth=5)
        child = parent.child("MA-013")
        assert child.depth == 1
        assert child.parent_context is parent
        assert child.call_chain == ["MA-013"]

    def test_child_inherits_bag_as_copy(self):
        parent = ExecutionContext(run_id="r1", bag={"key": "value"})
        child = parent.child("MA-013")
        assert child.bag["key"] == "value"
        # 修改子 bag 不影响父
        child.bag["new_key"] = "new_value"
        assert "new_key" not in parent.bag

    def test_child_has_empty_step_outputs(self):
        parent = ExecutionContext(run_id="r1")
        parent.step_outputs["s1"] = {"x": 1}
        child = parent.child("MA-013")
        assert child.step_outputs == {}

    def test_child_chain_accumulates(self):
        ctx = ExecutionContext(run_id="r1", max_depth=10)
        c1 = ctx.child("WF-001")
        c2 = c1.child("MA-013")
        c3 = c2.child("MA-014")
        assert c3.call_chain == ["WF-001", "MA-013", "MA-014"]
        assert c3.depth == 3

    def test_child_exceeds_max_depth(self):
        ctx = ExecutionContext(run_id="r1", max_depth=2)
        c1 = ctx.child("A")
        c2 = c1.child("B")
        with pytest.raises(RecursionLimitError, match="exceeds max 2"):
            c2.child("C")

    def test_child_exactly_at_max_depth(self):
        ctx = ExecutionContext(run_id="r1", max_depth=2)
        c1 = ctx.child("A")
        c2 = c1.child("B")
        # depth=2 == max_depth=2，刚好不超限
        assert c2.depth == 2
        # 再 child 才超限
        with pytest.raises(RecursionLimitError):
            c2.child("C")
```

---

## Step 7：验证

### 7.1 确保安装正常

```bash
pip install -e ".[dev]"
```

### 7.2 运行测试

```bash
# 只跑 Protocol 测试（不需要上游）
python -m pytest tests/protocol/ -v

# 跑全量测试（确认已有测试不被破坏）
python -m pytest -q
```

### 7.3 验证导入

```bash
python -c "
from agently_skills_runtime import (
    CapabilityKind, CapabilitySpec, CapabilityResult, CapabilityStatus,
    AgentSpec, AgentIOSchema, SkillSpec, WorkflowSpec,
    Step, LoopStep, ParallelStep, ConditionalStep, InputMapping,
    ExecutionContext, RecursionLimitError,
)
print('Protocol imports OK')

from agently_skills_runtime import AgentlySkillsRuntime, NodeReportV2
print('Bridge imports OK')
"
```

### 7.4 验证 Protocol 无上游依赖

```bash
# 确保 protocol/ 下没有 import agently 或 agent_sdk
grep -r "import agently" src/agently_skills_runtime/protocol/ && echo "FAIL: agently import found" || echo "OK: no agently import"
grep -r "import agent_sdk" src/agently_skills_runtime/protocol/ && echo "FAIL: agent_sdk import found" || echo "OK: no agent_sdk import"
```

---

## 完成标志

Phase 1 完成后，仓库应具备：
- ✅ `bridge.py`（原 runtime.py，重命名）
- ✅ `protocol/` 目录（5 个模块 + __init__.py）
- ✅ `errors.py`
- ✅ 更新后的 `__init__.py`（同时导出 Bridge + Protocol）
- ✅ Protocol 全量测试通过
- ✅ 已有桥接层测试不受影响
- ✅ 版本号保持 0.3.x（Protocol 只读就绪，暂不发 0.4.0）
