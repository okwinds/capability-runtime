# Codex 指令 — Phase 2：Runtime 层（Registry + Guards + Loop + Engine）

> 本阶段目标：建立 Runtime 层（能力注册表、执行守卫、循环控制器、调度引擎）+ 全量测试。
> 前置条件：Phase 1 已完成（Protocol 层 + bridge 重命名）。
> 约束：Runtime 层不 import 任何上游模块（agently / agent_sdk），只依赖 Protocol 层。

---

## 背景信息

### Phase 1 完成后的仓库结构

```
src/agently_skills_runtime/
├── __init__.py              ← 已更新，导出 Protocol + Bridge
├── bridge.py                ← 原 runtime.py（桥接层主入口）
├── types.py
├── config.py
├── errors.py                ← Phase 1 新增
├── protocol/                ← Phase 1 新增
│   ├── __init__.py
│   ├── capability.py
│   ├── skill.py
│   ├── agent.py
│   ├── workflow.py
│   └── context.py
├── adapters/
│   ├── agently_backend.py   ← 已有 ✅
│   ├── triggerflow_tool.py  ← 已有 ✅
│   └── upstream.py          ← 已有 ✅
└── reporting/
    └── node_report.py       ← 已有 ✅
```

### 不可违反的约束

1. **Runtime 层不 import agently 或 agent_sdk**，只 import `..protocol.*`
2. **所有文件以 `from __future__ import annotations` 开头**
3. **不修改任何已有文件**（protocol/、bridge.py、adapters/ 已有文件、reporting/、types.py、config.py）
4. **已有测试必须继续通过**

---

## Step 1：创建 runtime/ 目录结构

```bash
mkdir -p src/agently_skills_runtime/runtime
```

### 1.1 创建 `src/agently_skills_runtime/runtime/__init__.py`

```python
"""Runtime 层：能力注册、执行守卫、循环控制、调度引擎。"""
from __future__ import annotations

from .registry import CapabilityRegistry
from .guards import ExecutionGuards, LoopBreakerError
from .loop import LoopController
from .engine import CapabilityRuntime, RuntimeConfig, AdapterProtocol

__all__ = [
    "CapabilityRegistry",
    "ExecutionGuards",
    "LoopBreakerError",
    "LoopController",
    "CapabilityRuntime",
    "RuntimeConfig",
    "AdapterProtocol",
]
```

---

## Step 2：创建 `src/agently_skills_runtime/runtime/guards.py`

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
    这是 LoopStep.max_iterations 之上的第二道防线。

    例如：WF-001G 中 MA-024×60集 × MA-026×20镜头 × MA-027×20镜头 = 24000+ 次调用。
    ExecutionGuards 设总上限（如 50000）来兜底。
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

---

## Step 3：创建 `src/agently_skills_runtime/runtime/registry.py`

```python
"""能力注册表——所有 Spec 的中央存储和查询。"""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Union

from ..protocol.capability import CapabilityKind, CapabilitySpec
from ..protocol.skill import SkillSpec
from ..protocol.agent import AgentSpec
from ..protocol.workflow import (
    WorkflowSpec, Step, LoopStep, ParallelStep, ConditionalStep,
)

AnySpec = Union[SkillSpec, AgentSpec, WorkflowSpec]


def _get_base(spec: AnySpec) -> CapabilitySpec:
    """从具体 Spec 中提取公共 base。"""
    return spec.base


class CapabilityRegistry:
    """
    能力注册表。

    线程安全说明：当前为单线程设计（asyncio 单事件循环）。
    """

    def __init__(self) -> None:
        self._store: Dict[str, AnySpec] = {}

    def register(self, spec: AnySpec) -> None:
        """注册一个能力。重复注册同一 ID 会覆盖（last-write-wins）。"""
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
        - ParallelStep.branches 内的步骤
        - ConditionalStep.branches/default 内的步骤
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

---

## Step 4：创建 `src/agently_skills_runtime/runtime/loop.py`

```python
"""循环控制器——封装 LoopStep 的执行逻辑。"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List

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

        返回：CapabilityResult，output 为结果列表
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
                        metadata={
                            "completed_iterations": idx,
                            "total_planned": effective_max,
                        },
                    )
                elif fail_strategy == "skip":
                    errors.append({"index": idx, "error": result.error})
                    continue
                elif fail_strategy == "collect":
                    results.append(
                        {"status": "failed", "error": result.error, "index": idx}
                    )
                    continue

            results.append(result.output)

        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output=results,
            metadata={
                "completed_iterations": len(results),
                "total_planned": effective_max,
                "skipped_errors": errors if errors else None,
            },
        )
```

---

## Step 5：创建 `src/agently_skills_runtime/runtime/engine.py`

```python
"""CapabilityRuntime：能力组织层主入口。"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, runtime_checkable

from ..protocol.capability import (
    CapabilityKind,
    CapabilityResult,
    CapabilityStatus,
)
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
    - max_depth: 最大嵌套深度
    - max_total_loop_iterations: 全局循环迭代上限
    - default_loop_max_iterations: LoopStep 默认 max_iterations
    """
    max_depth: int = 10
    max_total_loop_iterations: int = 50000
    default_loop_max_iterations: int = 200


@runtime_checkable
class AdapterProtocol(Protocol):
    """
    Adapter 执行协议。所有 Adapter 必须实现此接口。

    参数说明：
    - spec: 具体的 Spec（AgentSpec/WorkflowSpec/SkillSpec）
    - input: 输入参数字典
    - context: 执行上下文
    - runtime: CapabilityRuntime 实例（供 Adapter 回调 _execute 实现递归调度）
    """
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
        self._guards = ExecutionGuards(
            max_total_loop_iterations=config.max_total_loop_iterations,
        )
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
        执行指定能力（顶层入口）。

        参数：
        - capability_id: 能力 ID
        - input: 输入参数
        - context_bag: 初始 context bag
        - run_id: 运行 ID（不指定则自动生成）
        - max_depth: 最大嵌套深度覆盖

        返回：CapabilityResult
        """
        self._guards.reset()

        spec = self.registry.get(capability_id)
        if spec is None:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"Capability not found: {capability_id!r}",
                metadata={"error_type": "not_found"},
            )

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
                spec=spec,
                input=input,
                context=child_ctx,
                runtime=self,
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
                metadata={
                    "error_type": "adapter_error",
                    "exception_class": type(exc).__name__,
                },
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

## Step 6：更新 `__init__.py` 导出 Runtime 层

在 `src/agently_skills_runtime/__init__.py` 中，追加以下导出（在 Protocol 导出之后、errors 导出之前）：

```python
# === Runtime 导出 ===
from .runtime.engine import CapabilityRuntime, RuntimeConfig, AdapterProtocol
from .runtime.registry import CapabilityRegistry
from .runtime.guards import ExecutionGuards, LoopBreakerError
from .runtime.loop import LoopController
```

并在 `__all__` 中追加：

```python
    # Runtime
    "CapabilityRuntime",
    "RuntimeConfig",
    "AdapterProtocol",
    "CapabilityRegistry",
    "ExecutionGuards",
    "LoopBreakerError",
    "LoopController",
```

---

## Step 7：创建 Runtime 测试

### 7.1 创建目录

```bash
mkdir -p tests/runtime
touch tests/runtime/__init__.py
```

### 7.2 创建 `tests/runtime/test_guards.py`

```python
"""ExecutionGuards 单元测试。"""
from __future__ import annotations

import pytest

from agently_skills_runtime.runtime.guards import ExecutionGuards, LoopBreakerError


def test_tick_increments_counter():
    g = ExecutionGuards(max_total_loop_iterations=100)
    g.tick()
    g.tick()
    g.tick()
    assert g.counter == 3


def test_tick_at_limit():
    g = ExecutionGuards(max_total_loop_iterations=3)
    g.tick()  # 1
    g.tick()  # 2
    g.tick()  # 3 — 恰好等于上限，不应抛异常
    assert g.counter == 3


def test_tick_exceeds_limit():
    g = ExecutionGuards(max_total_loop_iterations=3)
    g.tick()
    g.tick()
    g.tick()
    with pytest.raises(LoopBreakerError, match="limit.*3.*exceeded"):
        g.tick()  # 4 — 超限


def test_reset():
    g = ExecutionGuards(max_total_loop_iterations=5)
    g.tick()
    g.tick()
    assert g.counter == 2
    g.reset()
    assert g.counter == 0
    # 重置后可以继续
    g.tick()
    assert g.counter == 1
```

### 7.3 创建 `tests/runtime/test_registry.py`

```python
"""CapabilityRegistry 单元测试。"""
from __future__ import annotations

import pytest

from agently_skills_runtime.protocol.capability import (
    CapabilityKind, CapabilitySpec, CapabilityRef,
)
from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.protocol.skill import SkillSpec, SkillDispatchRule
from agently_skills_runtime.protocol.workflow import (
    WorkflowSpec, Step, LoopStep, ParallelStep, ConditionalStep,
)
from agently_skills_runtime.runtime.registry import CapabilityRegistry


def _make_agent(id: str, skills=None, collaborators=None, callable_workflows=None) -> AgentSpec:
    return AgentSpec(
        base=CapabilitySpec(id=id, kind=CapabilityKind.AGENT, name=id),
        skills=skills or [],
        collaborators=collaborators or [],
        callable_workflows=callable_workflows or [],
    )


def _make_skill(id: str, inject_to=None, dispatch_rules=None) -> SkillSpec:
    return SkillSpec(
        base=CapabilitySpec(id=id, kind=CapabilityKind.SKILL, name=id),
        source="inline content",
        source_type="inline",
        inject_to=inject_to or [],
        dispatch_rules=dispatch_rules or [],
    )


def _make_workflow(id: str, steps=None) -> WorkflowSpec:
    return WorkflowSpec(
        base=CapabilitySpec(id=id, kind=CapabilityKind.WORKFLOW, name=id),
        steps=steps or [],
    )


class TestRegistryCRUD:
    def test_register_and_get(self):
        reg = CapabilityRegistry()
        agent = _make_agent("MA-013")
        reg.register(agent)
        assert reg.get("MA-013") is agent

    def test_get_nonexistent_returns_none(self):
        reg = CapabilityRegistry()
        assert reg.get("nonexistent") is None

    def test_get_or_raise_nonexistent(self):
        reg = CapabilityRegistry()
        with pytest.raises(KeyError, match="nonexistent"):
            reg.get_or_raise("nonexistent")

    def test_register_overwrites(self):
        reg = CapabilityRegistry()
        a1 = _make_agent("X")
        a2 = _make_agent("X")
        reg.register(a1)
        reg.register(a2)
        assert reg.get("X") is a2

    def test_list_all(self):
        reg = CapabilityRegistry()
        reg.register(_make_agent("A"))
        reg.register(_make_skill("B"))
        assert len(reg.list_all()) == 2

    def test_list_by_kind(self):
        reg = CapabilityRegistry()
        reg.register(_make_agent("A"))
        reg.register(_make_agent("B"))
        reg.register(_make_skill("C"))
        assert len(reg.list_by_kind(CapabilityKind.AGENT)) == 2
        assert len(reg.list_by_kind(CapabilityKind.SKILL)) == 1
        assert len(reg.list_by_kind(CapabilityKind.WORKFLOW)) == 0

    def test_list_ids(self):
        reg = CapabilityRegistry()
        reg.register(_make_agent("A"))
        reg.register(_make_skill("B"))
        assert sorted(reg.list_ids()) == ["A", "B"]

    def test_has(self):
        reg = CapabilityRegistry()
        reg.register(_make_agent("A"))
        assert reg.has("A")
        assert not reg.has("B")

    def test_unregister(self):
        reg = CapabilityRegistry()
        reg.register(_make_agent("A"))
        assert reg.unregister("A") is True
        assert reg.has("A") is False
        assert reg.unregister("A") is False


class TestValidateDependencies:
    def test_no_dependencies_all_ok(self):
        reg = CapabilityRegistry()
        reg.register(_make_agent("A"))
        assert reg.validate_dependencies() == []

    def test_agent_missing_skill(self):
        reg = CapabilityRegistry()
        reg.register(_make_agent("A", skills=["missing-skill"]))
        assert reg.validate_dependencies() == ["missing-skill"]

    def test_agent_skill_present(self):
        reg = CapabilityRegistry()
        reg.register(_make_skill("s1"))
        reg.register(_make_agent("A", skills=["s1"]))
        assert reg.validate_dependencies() == []

    def test_agent_missing_collaborator(self):
        reg = CapabilityRegistry()
        reg.register(_make_agent("A", collaborators=[CapabilityRef(id="B")]))
        assert reg.validate_dependencies() == ["B"]

    def test_agent_missing_callable_workflow(self):
        reg = CapabilityRegistry()
        reg.register(_make_agent("A", callable_workflows=[CapabilityRef(id="WF-X")]))
        assert reg.validate_dependencies() == ["WF-X"]

    def test_workflow_missing_step_capability(self):
        reg = CapabilityRegistry()
        wf = _make_workflow("WF-1", steps=[
            Step(id="s1", capability=CapabilityRef(id="MA-001")),
            LoopStep(id="s2", capability=CapabilityRef(id="MA-002"), iterate_over="x"),
        ])
        reg.register(wf)
        assert sorted(reg.validate_dependencies()) == ["MA-001", "MA-002"]

    def test_workflow_parallel_step_deps(self):
        reg = CapabilityRegistry()
        wf = _make_workflow("WF-1", steps=[
            ParallelStep(id="p1", branches=[
                Step(id="b1", capability=CapabilityRef(id="A")),
                Step(id="b2", capability=CapabilityRef(id="B")),
            ]),
        ])
        reg.register(wf)
        assert sorted(reg.validate_dependencies()) == ["A", "B"]

    def test_workflow_conditional_step_deps(self):
        reg = CapabilityRegistry()
        wf = _make_workflow("WF-1", steps=[
            ConditionalStep(
                id="c1",
                condition_source="x",
                branches={"a": Step(id="b1", capability=CapabilityRef(id="A"))},
                default=Step(id="d1", capability=CapabilityRef(id="D")),
            ),
        ])
        reg.register(wf)
        assert sorted(reg.validate_dependencies()) == ["A", "D"]

    def test_skill_dispatch_rule_missing_target(self):
        reg = CapabilityRegistry()
        reg.register(_make_skill("s1", dispatch_rules=[
            SkillDispatchRule(condition="x", target=CapabilityRef(id="MISSING")),
        ]))
        assert reg.validate_dependencies() == ["MISSING"]

    def test_complex_mixed_dependencies(self):
        reg = CapabilityRegistry()
        reg.register(_make_skill("sk1"))
        reg.register(_make_agent("A", skills=["sk1", "sk2"]))  # sk2 missing
        reg.register(_make_workflow("WF", steps=[
            Step(id="s1", capability=CapabilityRef(id="A")),     # A present
            Step(id="s2", capability=CapabilityRef(id="B")),     # B missing
        ]))
        assert sorted(reg.validate_dependencies()) == ["B", "sk2"]


class TestFindSkillsInjectingTo:
    def test_find_matching(self):
        reg = CapabilityRegistry()
        s1 = _make_skill("s1", inject_to=["MA-013", "MA-014"])
        s2 = _make_skill("s2", inject_to=["MA-013"])
        s3 = _make_skill("s3", inject_to=["MA-015"])
        reg.register(s1)
        reg.register(s2)
        reg.register(s3)
        result = reg.find_skills_injecting_to("MA-013")
        assert len(result) == 2
        ids = [s.base.id for s in result]
        assert "s1" in ids
        assert "s2" in ids

    def test_find_no_match(self):
        reg = CapabilityRegistry()
        reg.register(_make_skill("s1", inject_to=["MA-015"]))
        assert reg.find_skills_injecting_to("MA-013") == []
```

### 7.4 创建 `tests/runtime/test_loop.py`

```python
"""LoopController 单元测试。"""
from __future__ import annotations

import pytest

from agently_skills_runtime.protocol.capability import CapabilityResult, CapabilityStatus
from agently_skills_runtime.runtime.guards import ExecutionGuards, LoopBreakerError
from agently_skills_runtime.runtime.loop import LoopController


@pytest.fixture
def guards():
    return ExecutionGuards(max_total_loop_iterations=1000)


@pytest.fixture
def controller(guards):
    return LoopController(guards=guards)


@pytest.mark.asyncio
async def test_normal_loop(controller):
    async def execute(item, idx):
        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output=f"processed-{item}",
        )

    result = await controller.run_loop(
        items=["a", "b", "c"],
        max_iterations=10,
        execute_fn=execute,
    )
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output == ["processed-a", "processed-b", "processed-c"]
    assert result.metadata["completed_iterations"] == 3


@pytest.mark.asyncio
async def test_max_iterations_limits_items(controller):
    async def execute(item, idx):
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=item)

    result = await controller.run_loop(
        items=[1, 2, 3, 4, 5],
        max_iterations=3,
        execute_fn=execute,
    )
    assert result.output == [1, 2, 3]
    assert result.metadata["completed_iterations"] == 3
    assert result.metadata["total_planned"] == 3


@pytest.mark.asyncio
async def test_abort_on_failure(controller):
    async def execute(item, idx):
        if idx == 1:
            return CapabilityResult(status=CapabilityStatus.FAILED, error="bad item")
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=item)

    result = await controller.run_loop(
        items=["a", "b", "c"],
        max_iterations=10,
        execute_fn=execute,
        fail_strategy="abort",
    )
    assert result.status == CapabilityStatus.FAILED
    assert "aborted at iteration 1" in result.error.lower()
    assert result.output == ["a"]  # 只有第一项成功


@pytest.mark.asyncio
async def test_skip_on_failure(controller):
    async def execute(item, idx):
        if idx == 1:
            return CapabilityResult(status=CapabilityStatus.FAILED, error="skip me")
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=item)

    result = await controller.run_loop(
        items=["a", "b", "c"],
        max_iterations=10,
        execute_fn=execute,
        fail_strategy="skip",
    )
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output == ["a", "c"]
    assert len(result.metadata["skipped_errors"]) == 1


@pytest.mark.asyncio
async def test_collect_on_failure(controller):
    async def execute(item, idx):
        if idx == 1:
            return CapabilityResult(status=CapabilityStatus.FAILED, error="collected")
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=item)

    result = await controller.run_loop(
        items=["a", "b", "c"],
        max_iterations=10,
        execute_fn=execute,
        fail_strategy="collect",
    )
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output[0] == "a"
    assert result.output[1]["status"] == "failed"
    assert result.output[2] == "c"


@pytest.mark.asyncio
async def test_exception_in_execute_fn(controller):
    async def execute(item, idx):
        raise ValueError("boom")

    result = await controller.run_loop(
        items=["a"],
        max_iterations=10,
        execute_fn=execute,
        fail_strategy="abort",
    )
    assert result.status == CapabilityStatus.FAILED
    assert "exception" in result.error.lower()


@pytest.mark.asyncio
async def test_global_guards_breaker():
    guards = ExecutionGuards(max_total_loop_iterations=2)
    controller = LoopController(guards=guards)

    async def execute(item, idx):
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=item)

    # 3 个 item 但 guards 允许 2 次
    with pytest.raises(LoopBreakerError):
        await controller.run_loop(
            items=["a", "b", "c"],
            max_iterations=10,
            execute_fn=execute,
        )


@pytest.mark.asyncio
async def test_empty_items(controller):
    async def execute(item, idx):
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=item)

    result = await controller.run_loop(
        items=[],
        max_iterations=10,
        execute_fn=execute,
    )
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output == []
```

### 7.5 创建 `tests/runtime/test_engine.py`

```python
"""CapabilityRuntime (Engine) 单元测试。"""
from __future__ import annotations

import pytest

from agently_skills_runtime.protocol.capability import (
    CapabilityKind, CapabilitySpec, CapabilityResult, CapabilityStatus,
)
from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.protocol.context import ExecutionContext
from agently_skills_runtime.runtime.engine import CapabilityRuntime, RuntimeConfig


class MockAdapter:
    """返回固定结果的 mock adapter。"""

    def __init__(self, output="mock_output"):
        self._output = output
        self.calls = []

    async def execute(self, *, spec, input, context, runtime):
        self.calls.append({"spec_id": spec.base.id, "input": input})
        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output=self._output,
        )


class FailAdapter:
    """总是失败的 adapter。"""

    async def execute(self, *, spec, input, context, runtime):
        return CapabilityResult(
            status=CapabilityStatus.FAILED,
            error="adapter failed",
        )


class ExceptionAdapter:
    """抛异常的 adapter。"""

    async def execute(self, *, spec, input, context, runtime):
        raise RuntimeError("unexpected boom")


def _make_agent(id: str) -> AgentSpec:
    return AgentSpec(
        base=CapabilitySpec(id=id, kind=CapabilityKind.AGENT, name=id),
    )


@pytest.mark.asyncio
async def test_run_dispatches_to_adapter():
    rt = CapabilityRuntime()
    adapter = MockAdapter(output="hello")
    rt.set_adapter(CapabilityKind.AGENT, adapter)
    rt.register(_make_agent("A"))

    result = await rt.run("A", input={"x": 1})

    assert result.status == CapabilityStatus.SUCCESS
    assert result.output == "hello"
    assert result.duration_ms is not None
    assert result.duration_ms > 0
    assert len(adapter.calls) == 1
    assert adapter.calls[0]["spec_id"] == "A"
    assert adapter.calls[0]["input"] == {"x": 1}


@pytest.mark.asyncio
async def test_run_not_found():
    rt = CapabilityRuntime()
    result = await rt.run("nonexistent")
    assert result.status == CapabilityStatus.FAILED
    assert "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_run_no_adapter():
    rt = CapabilityRuntime()
    rt.register(_make_agent("A"))
    # 不注入 adapter
    result = await rt.run("A")
    assert result.status == CapabilityStatus.FAILED
    assert "no adapter" in result.error.lower()


@pytest.mark.asyncio
async def test_run_adapter_exception():
    rt = CapabilityRuntime()
    rt.set_adapter(CapabilityKind.AGENT, ExceptionAdapter())
    rt.register(_make_agent("A"))

    result = await rt.run("A")
    assert result.status == CapabilityStatus.FAILED
    assert "unexpected boom" in result.error


@pytest.mark.asyncio
async def test_run_recursion_limit():
    """模拟递归超限：adapter 内递归调用 runtime._execute。"""

    class RecursiveAdapter:
        async def execute(self, *, spec, input, context, runtime):
            # 不断递归调用自己
            return await runtime._execute(spec, input=input, context=context)

    rt = CapabilityRuntime(config=RuntimeConfig(max_depth=3))
    rt.set_adapter(CapabilityKind.AGENT, RecursiveAdapter())
    rt.register(_make_agent("A"))

    result = await rt.run("A")
    assert result.status == CapabilityStatus.FAILED
    assert "recursion" in result.error.lower() or "depth" in result.error.lower()


@pytest.mark.asyncio
async def test_register_many():
    rt = CapabilityRuntime()
    rt.register_many([_make_agent("A"), _make_agent("B")])
    assert rt.registry.has("A")
    assert rt.registry.has("B")


@pytest.mark.asyncio
async def test_validate():
    rt = CapabilityRuntime()
    from agently_skills_runtime.protocol.capability import CapabilityRef
    rt.register(AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
        skills=["missing-skill"],
    ))
    missing = rt.validate()
    assert "missing-skill" in missing


@pytest.mark.asyncio
async def test_run_with_custom_run_id():
    rt = CapabilityRuntime()
    adapter = MockAdapter()
    rt.set_adapter(CapabilityKind.AGENT, adapter)
    rt.register(_make_agent("A"))

    result = await rt.run("A", run_id="my-run-123")
    assert result.status == CapabilityStatus.SUCCESS


@pytest.mark.asyncio
async def test_guards_reset_each_run():
    """确保每次 run 重置全局守卫。"""
    rt = CapabilityRuntime(config=RuntimeConfig(max_total_loop_iterations=10))

    class TickAdapter:
        async def execute(self, *, spec, input, context, runtime):
            for _ in range(5):
                runtime.guards.tick()
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output="ok")

    rt.set_adapter(CapabilityKind.AGENT, TickAdapter())
    rt.register(_make_agent("A"))

    r1 = await rt.run("A")
    assert r1.status == CapabilityStatus.SUCCESS
    assert rt.guards.counter == 5

    # 第二次 run 应该重置计数器
    r2 = await rt.run("A")
    assert r2.status == CapabilityStatus.SUCCESS
    assert rt.guards.counter == 5  # 重置后重新累计
```

---

## Step 8：验证

### 8.1 安装

```bash
pip install -e ".[dev]"
```

### 8.2 运行测试

```bash
# Runtime 层测试
python -m pytest tests/runtime/ -v

# 全量测试
python -m pytest -q
```

### 8.3 验证导入

```bash
python -c "
from agently_skills_runtime import (
    CapabilityRuntime, RuntimeConfig, AdapterProtocol,
    CapabilityRegistry, ExecutionGuards, LoopBreakerError, LoopController,
)
print('Runtime imports OK')
"
```

### 8.4 验证 Runtime 无上游依赖

```bash
grep -r "import agently" src/agently_skills_runtime/runtime/ && echo "FAIL" || echo "OK: no agently"
grep -r "import agent_sdk" src/agently_skills_runtime/runtime/ && echo "FAIL" || echo "OK: no agent_sdk"
```

---

## 完成标志

Phase 2 完成后，仓库应新增：
- ✅ `runtime/` 目录（4 个模块 + __init__.py）
- ✅ `__init__.py` 增加 Runtime 导出
- ✅ Runtime 全量测试通过
- ✅ 已有 Protocol + Bridge 测试不受影响
- ✅ Runtime 层无上游依赖
