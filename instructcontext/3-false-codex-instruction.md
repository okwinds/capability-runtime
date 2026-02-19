# Codex CLI 迭代指令：v0.3.1 能力组织层（Phase 1）

> 目标：在 v0.3.0 桥接主线之上，叠加"面向能力的组织层"（Protocol + Runtime + AgentAdapter），使框架具备声明→注册→调度→执行的完整闭环。
>
> 前提：v0.3.0 主线代码（`runtime.py` / `agently_backend.py` / `triggerflow_tool.py` / `types.py` / `config.py` / `reporting/`）不动，只新增。

---

## 指令正文

```
请阅读以下指令，严格按步骤执行。本轮任务是在 v0.3.0 桥接主线之上叠加"面向能力的组织层"。

## 核心约束（不可违反）

1. **不侵入上游**：不 fork/不修改 Agently 与 skills-runtime-sdk
2. **不重写桥接层**：v0.3.0 已有的 `src/agently_skills_runtime/runtime.py`、`adapters/agently_backend.py`、`adapters/triggerflow_tool.py`、`types.py`、`config.py`、`reporting/` 全部保留不动
3. **Protocol 和 Runtime 不依赖上游**：`protocol/` 和 `runtime/` 目录下的代码不 import agently 或 agent_sdk
4. **Adapters 可依赖上游**：`adapters/` 下的新 adapter 可 import 上游，但只用 Public API
5. **Python 3.10+**，使用 `from __future__ import annotations`
6. **TDD**：先写测试（RED），再实现（GREEN）
7. **版本号更新为 0.3.1**

## Step 1: 创建 protocol/（纯类型定义，不依赖上游）

创建 `src/agently_skills_runtime/protocol/` 目录，包含以下文件。
这些定义可直接复用 `legacy/2026-02-19-v0.2.0-self-contained/src/agently_skills_runtime/protocol/` 中的代码，因为 protocol 层的设计是正确的。

### protocol/__init__.py
空文件或导入汇总。

### protocol/capability.py
```python
"""三种元能力共享的统一接口。"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

class CapabilityKind(str, Enum):
    SKILL = "skill"
    AGENT = "agent"
    WORKFLOW = "workflow"

@dataclass(frozen=True)
class CapabilityRef:
    id: str
    kind: Optional[CapabilityKind] = None

@dataclass(frozen=True)
class CapabilitySpec:
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
    status: CapabilityStatus
    output: Any = None
    error: Optional[str] = None
    report: Optional[Any] = None
    artifacts: List[str] = field(default_factory=list)
```

### protocol/skill.py
```python
"""Skills 元能力声明。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from .capability import CapabilitySpec, CapabilityRef

@dataclass(frozen=True)
class SkillDispatchRule:
    condition: str
    target: CapabilityRef
    priority: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class SkillSpec:
    base: CapabilitySpec
    source: str
    source_type: str = "file"           # file | inline | uri
    dispatch_rules: List[SkillDispatchRule] = field(default_factory=list)
    inject_to: List[str] = field(default_factory=list)
```

### protocol/agent.py
```python
"""Agent 元能力声明。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from .capability import CapabilitySpec, CapabilityRef

@dataclass(frozen=True)
class AgentIOSchema:
    fields: Dict[str, str] = field(default_factory=dict)
    required: List[str] = field(default_factory=list)

@dataclass(frozen=True)
class AgentSpec:
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

### protocol/workflow.py
```python
"""Workflow 元能力声明。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from .capability import CapabilitySpec, CapabilityRef

@dataclass(frozen=True)
class InputMapping:
    source: str
    target_field: str

@dataclass(frozen=True)
class Step:
    id: str
    capability: CapabilityRef
    input_mappings: List[InputMapping] = field(default_factory=list)

@dataclass(frozen=True)
class LoopStep:
    id: str
    capability: CapabilityRef
    iterate_over: str
    item_input_mappings: List[InputMapping] = field(default_factory=list)
    max_iterations: int = 100
    collect_as: str = "results"

@dataclass(frozen=True)
class ParallelStep:
    id: str
    branches: List[Union[Step, LoopStep]] = field(default_factory=list)
    join_strategy: str = "all_success"

@dataclass(frozen=True)
class ConditionalStep:
    id: str
    condition_source: str
    branches: Dict[str, Union[Step, LoopStep]] = field(default_factory=dict)
    default: Optional[Union[Step, LoopStep]] = None

WorkflowStep = Union[Step, LoopStep, ParallelStep, ConditionalStep]

@dataclass(frozen=True)
class WorkflowSpec:
    base: CapabilitySpec
    steps: List[WorkflowStep] = field(default_factory=list)
    context_schema: Optional[Dict[str, str]] = None
    output_mappings: List[InputMapping] = field(default_factory=list)
```

### protocol/context.py
```python
"""执行上下文。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

class RecursionLimitError(Exception):
    pass

@dataclass
class ExecutionContext:
    run_id: str
    parent_context: Optional[ExecutionContext] = None
    depth: int = 0
    max_depth: int = 10
    bag: Dict[str, Any] = field(default_factory=dict)
    step_outputs: Dict[str, Any] = field(default_factory=dict)
    call_chain: List[str] = field(default_factory=list)

    def child(self, capability_id: str) -> ExecutionContext:
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
        """解析映射表达式（6 种前缀）。"""
        if expression.startswith("context."):
            key = expression[len("context."):]
            return self.bag.get(key)
        elif expression.startswith("previous."):
            key = expression[len("previous."):]
            if not self.step_outputs:
                return None
            last_key = list(self.step_outputs.keys())[-1]
            last_out = self.step_outputs[last_key]
            return last_out.get(key) if isinstance(last_out, dict) else None
        elif expression.startswith("step."):
            rest = expression[len("step."):]
            parts = rest.split(".", 1)
            step_id = parts[0]
            key = parts[1] if len(parts) > 1 else None
            out = self.step_outputs.get(step_id)
            if key and isinstance(out, dict):
                return out.get(key)
            return out
        elif expression.startswith("literal."):
            return expression[len("literal."):]
        elif expression == "item":
            return self.bag.get("__current_item__")
        elif expression.startswith("item."):
            key = expression[len("item."):]
            item = self.bag.get("__current_item__")
            return item.get(key) if isinstance(item, dict) else None
        return None
```

## Step 2: 创建 runtime/（执行引擎，不依赖上游）

### runtime/__init__.py
空文件。

### runtime/guards.py
```python
"""执行守卫。"""
from __future__ import annotations

class LoopBreakerError(Exception):
    pass

class ExecutionGuards:
    def __init__(self, *, max_total_loop_iterations: int = 10000):
        self._max = max_total_loop_iterations
        self._counter = 0

    def tick(self) -> None:
        self._counter += 1
        if self._counter > self._max:
            raise LoopBreakerError(f"Global loop limit {self._max} exceeded")

    @property
    def counter(self) -> int:
        return self._counter
```

### runtime/loop.py
```python
"""循环控制器。"""
from __future__ import annotations
from typing import Any, Awaitable, Callable, Dict, List
from ..protocol.capability import CapabilityResult, CapabilityStatus
from .guards import ExecutionGuards

class LoopController:
    def __init__(self, *, guards: ExecutionGuards):
        self._guards = guards

    async def run_loop(
        self,
        *,
        items: List[Any],
        max_iterations: int,
        execute_fn: Callable[[Any, int], Awaitable[CapabilityResult]],
    ) -> CapabilityResult:
        results: List[Any] = []
        effective_max = min(max_iterations, len(items))
        for idx, item in enumerate(items[:effective_max]):
            self._guards.tick()
            result = await execute_fn(item, idx)
            if result.status == CapabilityStatus.FAILED:
                return CapabilityResult(
                    status=CapabilityStatus.FAILED,
                    output=results,
                    error=f"Loop iteration {idx} failed: {result.error}",
                )
            results.append(result.output)
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=results)
```

### runtime/registry.py
```python
"""能力注册表。"""
from __future__ import annotations
from typing import Dict, List, Optional, Union
from ..protocol.capability import CapabilityKind, CapabilitySpec
from ..protocol.skill import SkillSpec
from ..protocol.agent import AgentSpec
from ..protocol.workflow import WorkflowSpec

AnySpec = Union[SkillSpec, AgentSpec, WorkflowSpec]

def _get_base(spec: AnySpec) -> CapabilitySpec:
    return spec.base

class CapabilityRegistry:
    def __init__(self) -> None:
        self._store: Dict[str, AnySpec] = {}

    def register(self, spec: AnySpec) -> None:
        base = _get_base(spec)
        self._store[base.id] = spec

    def get(self, capability_id: str) -> Optional[AnySpec]:
        return self._store.get(capability_id)

    def get_or_raise(self, capability_id: str) -> AnySpec:
        spec = self.get(capability_id)
        if spec is None:
            raise KeyError(f"Capability not found: {capability_id}")
        return spec

    def list_by_kind(self, kind: CapabilityKind) -> List[AnySpec]:
        return [s for s in self._store.values() if _get_base(s).kind == kind]

    def validate_dependencies(self) -> List[str]:
        """校验所有能力的依赖是否已注册。返回缺失 ID 列表。"""
        missing: List[str] = []
        for spec in self._store.values():
            base = _get_base(spec)
            deps: List[str] = []
            if isinstance(spec, AgentSpec):
                deps.extend(spec.skills)
                deps.extend(r.id for r in spec.collaborators)
                deps.extend(r.id for r in spec.callable_workflows)
            elif isinstance(spec, WorkflowSpec):
                for step in spec.steps:
                    if hasattr(step, "capability"):
                        deps.append(step.capability.id)
                    if hasattr(step, "branches") and isinstance(step.branches, list):
                        for b in step.branches:
                            if hasattr(b, "capability"):
                                deps.append(b.capability.id)
                    if hasattr(step, "branches") and isinstance(step.branches, dict):
                        for b in step.branches.values():
                            if hasattr(b, "capability"):
                                deps.append(b.capability.id)
                    if hasattr(step, "default") and step.default and hasattr(step.default, "capability"):
                        deps.append(step.default.capability.id)
            for dep_id in deps:
                if dep_id not in self._store and dep_id not in missing:
                    missing.append(dep_id)
        return missing
```

### runtime/engine.py
```python
"""CapabilityRuntime：能力组织层主入口。"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Dict, Optional, Protocol
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
    max_loop_iterations: int = 200
    max_depth: int = 10
    max_total_loop_iterations: int = 10000

class AdapterProtocol(Protocol):
    async def execute(self, *, spec: Any, input: Dict[str, Any], context: ExecutionContext, runtime: CapabilityRuntime) -> CapabilityResult: ...

class CapabilityRuntime:
    def __init__(self, *, config: RuntimeConfig = RuntimeConfig()):
        self.config = config
        self.registry = CapabilityRegistry()
        self._guards = ExecutionGuards(max_total_loop_iterations=config.max_total_loop_iterations)
        self._loop_controller = LoopController(guards=self._guards)
        self._adapters: Dict[CapabilityKind, AdapterProtocol] = {}

    def set_adapter(self, kind: CapabilityKind, adapter: AdapterProtocol) -> None:
        self._adapters[kind] = adapter

    def register(self, spec: AnySpec) -> None:
        self.registry.register(spec)

    def validate(self) -> list[str]:
        return self.registry.validate_dependencies()

    async def run(
        self,
        capability_id: str,
        *,
        input: Optional[Dict[str, Any]] = None,
        context_bag: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        max_depth: Optional[int] = None,
    ) -> CapabilityResult:
        spec = self.registry.get_or_raise(capability_id)
        base = _get_base(spec)
        ctx = ExecutionContext(
            run_id=run_id or uuid.uuid4().hex,
            max_depth=max_depth or self.config.max_depth,
            bag=dict(context_bag or {}),
        )
        return await self._execute(spec, input=input or {}, context=ctx)

    async def _execute(
        self,
        spec: AnySpec,
        *,
        input: Dict[str, Any],
        context: ExecutionContext,
    ) -> CapabilityResult:
        base = _get_base(spec)
        child_ctx = context.child(base.id)
        adapter = self._adapters.get(base.kind)
        if adapter is None:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"No adapter registered for kind: {base.kind}",
            )
        try:
            return await adapter.execute(spec=spec, input=input, context=child_ctx, runtime=self)
        except RecursionLimitError as exc:
            return CapabilityResult(status=CapabilityStatus.FAILED, error=str(exc))
        except LoopBreakerError as exc:
            return CapabilityResult(status=CapabilityStatus.FAILED, error=str(exc))

    @property
    def loop_controller(self) -> LoopController:
        return self._loop_controller
```

## Step 3: 创建 adapters/agent_adapter.py（桥接到已有的 AgentlySkillsRuntime）

```python
"""
AgentAdapter：把 AgentSpec 的声明式调用桥接到已有的 AgentlySkillsRuntime 执行。

关键：不自己实现 LLM 调用，而是委托已有的桥接层。
"""
from __future__ import annotations
from typing import Any, Dict
from ..protocol.agent import AgentSpec
from ..protocol.capability import CapabilityResult, CapabilityStatus
from ..protocol.context import ExecutionContext


class AgentAdapter:
    """
    Agent 适配器。

    宿主注入一个 runner 函数，该函数负责实际执行 Agent（通常是 AgentlySkillsRuntime.run_async）。
    框架只负责从 AgentSpec 构造调用参数，然后委托 runner 执行。
    """

    def __init__(self, *, runner=None):
        """
        参数：
        - runner: async callable(task: str, **kwargs) -> Any
          通常是 AgentlySkillsRuntime.run_async 或其包装。
          如果 runner 为 None，execute() 将返回 FAILED。
        """
        self._runner = runner

    async def execute(
        self,
        *,
        spec: AgentSpec,
        input: Dict[str, Any],
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        if self._runner is None:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error="AgentAdapter: no runner injected",
            )

        # 从 input 构造 task 文本（业务层可通过 input["task"] 传入）
        task = input.get("task", "")
        if not task and input:
            # 如果没有 task 字段，把整个 input 序列化为 context 描述
            import json
            task = json.dumps(input, ensure_ascii=False, default=str)

        try:
            result = await self._runner(task)
            # 兼容 NodeResultV2 和普通返回值
            if hasattr(result, "node_report"):
                output = getattr(result, "final_output", None) or getattr(result.node_report, "meta", {}).get("final_output")
                status = CapabilityStatus.SUCCESS if result.node_report.status == "success" else CapabilityStatus.FAILED
                return CapabilityResult(status=status, output=output, report=result.node_report)
            else:
                return CapabilityResult(status=CapabilityStatus.SUCCESS, output=result)
        except Exception as exc:
            return CapabilityResult(status=CapabilityStatus.FAILED, error=str(exc))
```

## Step 4: 更新入口和版本

### 更新 `src/agently_skills_runtime/__init__.py`

在已有的导出基础上，追加 protocol + runtime 的导出：

```python
# === 已有导出（桥接层，不动）===
from .runtime import AgentlySkillsRuntime
from .types import NodeReportV2, NodeResultV2

# === 新增导出（能力组织层）===
from .protocol.capability import CapabilitySpec, CapabilityKind, CapabilityRef, CapabilityResult, CapabilityStatus
from .protocol.skill import SkillSpec, SkillDispatchRule
from .protocol.agent import AgentSpec, AgentIOSchema
from .protocol.workflow import WorkflowSpec, Step, LoopStep, ParallelStep, ConditionalStep, InputMapping, WorkflowStep
from .protocol.context import ExecutionContext, RecursionLimitError
from .runtime_engine import CapabilityRuntime, RuntimeConfig  # 注意：避免与 runtime.py 冲突

__all__ = [
    # Bridge layer
    "AgentlySkillsRuntime", "NodeReportV2", "NodeResultV2",
    # Protocol
    "CapabilitySpec", "CapabilityKind", "CapabilityRef", "CapabilityResult", "CapabilityStatus",
    "SkillSpec", "SkillDispatchRule",
    "AgentSpec", "AgentIOSchema",
    "WorkflowSpec", "Step", "LoopStep", "ParallelStep", "ConditionalStep", "InputMapping", "WorkflowStep",
    "ExecutionContext", "RecursionLimitError",
    # Runtime (capability engine)
    "CapabilityRuntime", "RuntimeConfig",
]
```

**注意**：由于已有的 `runtime.py` 文件名与 `runtime/` 目录冲突，有两个解决方案：
- 方案 A（推荐）：把已有的 `runtime.py` 重命名为 `bridge.py`（同时更新 `__init__.py` 的 import）
- 方案 B：把 `runtime/` 目录改名为 `capability_runtime/`

选择方案 A，因为它更清晰地表达了桥接层的身份。具体操作：
1. `mv src/agently_skills_runtime/runtime.py src/agently_skills_runtime/bridge.py`
2. 更新 `__init__.py`：`from .bridge import AgentlySkillsRuntime`
3. 更新所有 import 了 `.runtime` 的测试文件

### 更新 pyproject.toml
- version 改为 `"0.3.1"`

## Step 5: 编写测试

### tests/protocol/test_capability.py
- CapabilitySpec 构造、CapabilityResult 字段
- CapabilityKind 枚举值

### tests/protocol/test_context.py
- resolve_mapping 所有 6 种前缀
- child() 递归限制

### tests/protocol/test_workflow.py
- WorkflowSpec 构造、Step/LoopStep/ParallelStep/ConditionalStep

### tests/runtime/test_registry.py
- register / get / get_or_raise / list_by_kind
- validate_dependencies（含缺失依赖检测）

### tests/runtime/test_guards.py
- ExecutionGuards.tick() 正常和超限
- LoopBreakerError

### tests/runtime/test_loop.py
- LoopController 正常循环
- max_iterations 超限
- 迭代失败中止 + partial 输出

### tests/runtime/test_engine.py
- 使用 mock adapter 测试分发逻辑
- 无 adapter 返回 FAILED
- RecursionLimitError 处理

### tests/adapters/test_agent_adapter_bridge.py
- 使用 mock runner 测试 AgentAdapter
- runner 为 None 返回 FAILED
- runner 抛异常返回 FAILED

### tests/scenarios/test_workflow_with_loop.py
- 模拟 Workflow: 2 个 Agent + 循环（全 mock，不依赖上游）

## Step 6: 清理与文档

1. 更新 README.md：说明 v0.3.1 新增了能力组织层
2. 更新 DOCS_INDEX.md：登记新增文件
3. 更新 docs/worklog.md：记录本轮变更
4. 创建 docs/task-summaries/2026-02-19-capability-organization-layer.md

## 验收标准

1. `pip install -e .` 成功
2. `pytest -q` 全部通过
3. 已有的桥接层测试不受影响（所有旧测试继续通过）
4. 以下代码可运行：
```python
from agently_skills_runtime import (
    CapabilityRuntime, RuntimeConfig,
    AgentSpec, CapabilitySpec, CapabilityKind,
)

runtime = CapabilityRuntime(config=RuntimeConfig())
spec = AgentSpec(
    base=CapabilitySpec(id="my-agent", kind=CapabilityKind.AGENT, name="Test Agent"),
)
runtime.register(spec)
assert runtime.validate() == []
# await runtime.run("my-agent", input={"task": "hello"}) — 需要注入 adapter
```
```

---

## 执行方式

### 一次性执行（推荐）
```bash
cd /path/to/agently-skills-runtime

# 把上面的指令保存为文件
cat > CODEX_INSTRUCTION.md << 'EOF'
# （把上面"指令正文"部分的内容粘贴到这里）
EOF

codex --model claude-sonnet-4-20250514 \
  "请阅读仓库根目录的 CODEX_INSTRUCTION.md，严格按照步骤顺序实施。先读完全文再开始编码。注意：runtime.py 已存在，新增的 runtime/ 目录需要处理命名冲突（按指令中的方案 A 执行）。"
```

### 分步执行（更可控）
```bash
# Phase 1: Protocol 层
codex "阅读 CODEX_INSTRUCTION.md。只执行 Step 1: 创建 protocol/ 目录下的所有文件。不要修改任何已有文件。"

# Phase 2: Runtime 层
codex "阅读 CODEX_INSTRUCTION.md。执行 Step 2: 创建 runtime/ 目录（registry, guards, loop, engine）。注意处理与已有 runtime.py 的命名冲突。"

# Phase 3: Adapter + 入口更新
codex "阅读 CODEX_INSTRUCTION.md。执行 Step 3-4: 创建 agent_adapter.py，更新 __init__.py，处理 runtime.py → bridge.py 重命名。"

# Phase 4: 测试 + 清理
codex "阅读 CODEX_INSTRUCTION.md。执行 Step 5-6: 编写所有测试，更新文档。确保 pytest -q 全部通过。"
```
