# Codex 指令 — Phase 3：Adapter 层 + 场景测试

> 本阶段目标：实现 AgentAdapter、WorkflowAdapter、SkillAdapter + 场景集成测试。
> 前置条件：Phase 1（Protocol）和 Phase 2（Runtime）已完成。
> 关键区别：Adapter 层是唯一允许 import 上游的层（但 Phase 3 的测试全部用 mock，不真正调用上游）。

---

## 背景信息

### Phase 2 完成后的仓库结构

```
src/agently_skills_runtime/
├── __init__.py
├── bridge.py                ← 桥接层主入口
├── types.py
├── config.py
├── errors.py
├── protocol/                ← Phase 1 ✅
│   ├── capability.py
│   ├── skill.py
│   ├── agent.py
│   ├── workflow.py
│   └── context.py
├── runtime/                 ← Phase 2 ✅
│   ├── engine.py            ← CapabilityRuntime
│   ├── registry.py          ← CapabilityRegistry
│   ├── guards.py            ← ExecutionGuards
│   └── loop.py              ← LoopController
├── adapters/
│   ├── agently_backend.py   ← 已有 ✅
│   ├── triggerflow_tool.py  ← 已有 ✅
│   └── upstream.py          ← 已有 ✅
└── reporting/
    └── node_report.py       ← 已有 ✅
```

### Adapter 层设计原则

1. **AgentAdapter** — 把 AgentSpec 的声明翻译为对桥接层的真实调用。接受一个 `runner` 函数注入（通常是 `AgentlySkillsRuntime.run_async`），构造 task 文本后委托 runner 执行。
2. **WorkflowAdapter** — 把 WorkflowSpec 的步骤编排翻译为对 `CapabilityRuntime._execute()` 的递归调用。自身不 import 上游。
3. **SkillAdapter** — 加载 Skill 内容，可选触发 dispatch_rules。

### 不可违反的约束

1. **不修改已有的 adapters/agently_backend.py、adapters/triggerflow_tool.py、adapters/upstream.py**
2. **WorkflowAdapter 不 import 上游**——它只通过 `runtime._execute()` 间接调用
3. **测试全部用 mock runner**——不依赖真实 LLM 或上游 SDK Agent
4. **所有文件以 `from __future__ import annotations` 开头**

---

## Step 1：创建 `src/agently_skills_runtime/adapters/agent_adapter.py`

```python
"""Agent 适配器：AgentSpec → Bridge Runtime 执行。"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Dict, List, Optional

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
      也可以传入任何兼容签名的 async callable（方便测试）。
    - skill_content_loader: 可选的 Skill 内容加载函数。签名：
        def loader(spec: SkillSpec) -> str
      如果不提供，则 skill 注入使用 spec.source 字段作为内容。
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
        """
        执行 AgentSpec。

        流程：
        1. 合并 Skills（spec.skills + inject_to 匹配）
        2. 加载 Skill 内容
        3. 构造 task 文本（prompt_template + input + skills + output_schema）
        4. 构造 initial_history（如有 system_prompt）
        5. 委托 runner 执行
        6. 包装返回值为 CapabilityResult
        """
        if self._runner is None:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=(
                    "AgentAdapter: no runner injected. "
                    "Inject AgentlySkillsRuntime.run_async or a compatible async callable."
                ),
            )

        # 1. 合并 Skills
        skill_ids = list(spec.skills)
        if hasattr(runtime, "registry"):
            injecting_skills = runtime.registry.find_skills_injecting_to(spec.base.id)
            for s in injecting_skills:
                if s.base.id not in skill_ids:
                    skill_ids.append(s.base.id)

        # 2. 加载 Skill 内容
        skill_contents: List[str] = []
        for sid in skill_ids:
            if hasattr(runtime, "registry"):
                skill_spec = runtime.registry.get(sid)
                if isinstance(skill_spec, SkillSpec):
                    if self._skill_content_loader:
                        try:
                            content = self._skill_content_loader(skill_spec)
                        except Exception:
                            content = skill_spec.source
                    else:
                        content = skill_spec.source
                    skill_contents.append(
                        f"[Skill: {skill_spec.base.name}]\n{content}"
                    )

        # 3. 构造 task 文本
        task = self._build_task(spec=spec, input=input, skill_contents=skill_contents)

        # 4. 构造 initial_history
        initial_history = None
        if spec.system_prompt:
            initial_history = [{"role": "system", "content": spec.system_prompt}]

        # 5. 委托 runner 执行
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
                parts.append(spec.prompt_template)
                parts.append(
                    f"\n输入参数:\n{json.dumps(input, ensure_ascii=False, indent=2)}"
                )
        else:
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
            parts.append("\n\n请按以下格式输出 JSON：")
            schema_desc = json.dumps(
                {k: f"({v})" for k, v in spec.output_schema.fields.items()},
                ensure_ascii=False,
                indent=2,
            )
            parts.append(schema_desc)

        return "\n".join(parts)

    def _wrap_result(self, result: Any) -> CapabilityResult:
        """把桥接层返回值包装为 CapabilityResult。"""
        # 兼容 NodeResultV2（bridge.py 的返回值）
        if hasattr(result, "node_report"):
            nr = result.node_report
            output = getattr(result, "final_output", None)
            if output is None and hasattr(nr, "meta"):
                output = nr.meta.get("final_output")
            status = (
                CapabilityStatus.SUCCESS
                if getattr(nr, "status", None) == "success"
                else CapabilityStatus.FAILED
            )
            error = getattr(nr, "reason", None) if status == CapabilityStatus.FAILED else None
            return CapabilityResult(
                status=status, output=output, error=error, report=nr,
            )

        # 兼容普通返回值
        if isinstance(result, str):
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output=result)
        if isinstance(result, dict):
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output=result)

        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=result)
```

---

## Step 2：创建 `src/agently_skills_runtime/adapters/workflow_adapter.py`

```python
"""Workflow 适配器：WorkflowSpec → 步骤编排执行。"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from ..protocol.workflow import (
    WorkflowSpec,
    Step,
    LoopStep,
    ParallelStep,
    ConditionalStep,
    InputMapping,
)
from ..protocol.capability import CapabilityResult, CapabilityStatus
from ..protocol.context import ExecutionContext


class WorkflowAdapter:
    """
    Workflow 适配器。

    不依赖任何上游——所有执行都通过 runtime._execute() 递归回 Engine。
    """

    async def execute(
        self,
        *,
        spec: WorkflowSpec,
        input: Dict[str, Any],
        context: ExecutionContext,
        runtime: Any,  # CapabilityRuntime
    ) -> CapabilityResult:
        """
        执行 WorkflowSpec。

        流程：
        1. 合并 input 到 context bag
        2. 遍历 steps，按类型分发执行
        3. 每步结果缓存到 context.step_outputs
        4. 步骤失败 → 立即返回
        5. 全部完成 → 解析 output_mappings 构造最终输出
        """
        context.bag.update(input)

        for step in spec.steps:
            result = await self._execute_step(step, context=context, runtime=runtime)
            if result.status == CapabilityStatus.FAILED:
                return result

        output = self._resolve_output_mappings(spec.output_mappings, context)
        if output is None:
            output = dict(context.step_outputs)

        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=output)

    async def _execute_step(
        self,
        step: Any,
        *,
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """按步骤类型分发执行。"""
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
        self,
        step: Step,
        *,
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """执行基础步骤。"""
        step_input = self._resolve_input_mappings(step.input_mappings, context)

        target_spec = runtime.registry.get_or_raise(step.capability.id)
        result = await runtime._execute(target_spec, input=step_input, context=context)

        context.step_outputs[step.id] = result.output
        return result

    async def _execute_loop_step(
        self,
        step: LoopStep,
        *,
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """执行循环步骤。"""
        items = context.resolve_mapping(step.iterate_over)
        if not isinstance(items, list):
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=(
                    f"LoopStep '{step.id}': iterate_over resolved to "
                    f"{type(items).__name__}, expected list"
                ),
            )

        target_spec = runtime.registry.get_or_raise(step.capability.id)

        async def execute_item(item: Any, idx: int) -> CapabilityResult:
            item_context = ExecutionContext(
                run_id=context.run_id,
                parent_context=context,
                depth=context.depth,
                max_depth=context.max_depth,
                bag={**context.bag, "__current_item__": item},
                step_outputs=dict(context.step_outputs),
                call_chain=list(context.call_chain),
            )
            step_input = self._resolve_input_mappings(
                step.item_input_mappings, item_context,
            )
            if not step_input:
                step_input = item if isinstance(item, dict) else {"item": item}
            return await runtime._execute(
                target_spec, input=step_input, context=item_context,
            )

        result = await runtime.loop_controller.run_loop(
            items=items,
            max_iterations=step.max_iterations,
            execute_fn=execute_item,
            fail_strategy=step.fail_strategy,
        )

        context.step_outputs[step.id] = result.output
        return result

    async def _execute_parallel_step(
        self,
        step: ParallelStep,
        *,
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """执行并行步骤。"""
        tasks = []
        for branch in step.branches:
            tasks.append(
                self._execute_step(branch, context=context, runtime=runtime)
            )

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        branch_results: List[CapabilityResult] = []
        for r in raw_results:
            if isinstance(r, Exception):
                branch_results.append(
                    CapabilityResult(status=CapabilityStatus.FAILED, error=str(r))
                )
            else:
                branch_results.append(r)

        if step.join_strategy == "all_success":
            failed = [r for r in branch_results if r.status == CapabilityStatus.FAILED]
            if failed:
                return CapabilityResult(
                    status=CapabilityStatus.FAILED,
                    output=[r.output for r in branch_results],
                    error=(
                        f"ParallelStep '{step.id}': "
                        f"{len(failed)}/{len(branch_results)} branches failed"
                    ),
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
        self,
        step: ConditionalStep,
        *,
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """执行条件步骤。"""
        condition_value = context.resolve_mapping(step.condition_source)
        condition_key = str(condition_value) if condition_value is not None else ""

        branch = step.branches.get(condition_key, step.default)
        if branch is None:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=(
                    f"ConditionalStep '{step.id}': no branch for "
                    f"condition '{condition_key}' and no default"
                ),
            )

        result = await self._execute_step(branch, context=context, runtime=runtime)
        context.step_outputs[step.id] = result.output
        return result

    @staticmethod
    def _resolve_input_mappings(
        mappings: List[InputMapping],
        context: ExecutionContext,
    ) -> Dict[str, Any]:
        """解析输入映射列表。"""
        result: Dict[str, Any] = {}
        for m in mappings:
            value = context.resolve_mapping(m.source)
            result[m.target_field] = value
        return result

    @staticmethod
    def _resolve_output_mappings(
        mappings: List[InputMapping],
        context: ExecutionContext,
    ) -> Any:
        """解析输出映射列表。"""
        if not mappings:
            return None
        result: Dict[str, Any] = {}
        for m in mappings:
            value = context.resolve_mapping(m.source)
            result[m.target_field] = value
        return result
```

---

## Step 3：创建 `src/agently_skills_runtime/adapters/skill_adapter.py`

```python
"""Skill 适配器：SkillSpec → 内容加载 + 可选 dispatch。"""
from __future__ import annotations

import os
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
        """执行 SkillSpec。"""
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
                    result = await runtime._execute(
                        target_spec, input=input, context=context,
                    )
                    dispatched_results.append(
                        {"target": rule.target.id, "result": result.output}
                    )
                except Exception as exc:
                    dispatched_results.append(
                        {"target": rule.target.id, "error": str(exc)}
                    )

        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output=content,
            metadata={"dispatched": dispatched_results} if dispatched_results else {},
        )

    def _load_content(self, spec: SkillSpec) -> str:
        """加载 Skill 内容。"""
        if spec.source_type == "inline":
            return spec.source
        elif spec.source_type == "file":
            path = os.path.join(self._workspace_root, spec.source)
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        elif spec.source_type == "uri":
            raise NotImplementedError(
                "URI loading requires allowlist authorization (safe-by-default)"
            )
        else:
            raise ValueError(f"Unknown source_type: {spec.source_type}")

    @staticmethod
    def _evaluate_condition(condition: str, context: ExecutionContext) -> bool:
        """Phase 1: 简单条件评估——检查 context bag 中 key 是否存在且 truthy。"""
        value = context.bag.get(condition)
        return bool(value)
```

---

## Step 4：更新 `src/agently_skills_runtime/adapters/__init__.py`

```python
"""Adapters：桥接上游与能力组织层。"""
from __future__ import annotations

# 已有桥接适配器（不修改）
# from .agently_backend import AgentlyChatBackend
# from .triggerflow_tool import ...

# 新增能力适配器
from .agent_adapter import AgentAdapter
from .workflow_adapter import WorkflowAdapter
from .skill_adapter import SkillAdapter

__all__ = [
    "AgentAdapter",
    "WorkflowAdapter",
    "SkillAdapter",
]
```

**注意**：如果已有的 `adapters/__init__.py` 有内容，保持已有内容，追加新的导出。

---

## Step 5：更新顶层 `__init__.py`

在 `src/agently_skills_runtime/__init__.py` 中追加：

```python
# === Adapter 导出 ===
from .adapters.agent_adapter import AgentAdapter
from .adapters.workflow_adapter import WorkflowAdapter
from .adapters.skill_adapter import SkillAdapter
```

并在 `__all__` 中追加：

```python
    # Adapters
    "AgentAdapter",
    "WorkflowAdapter",
    "SkillAdapter",
```

---

## Step 6：创建 Adapter 测试

### 6.1 创建目录

```bash
mkdir -p tests/adapters
touch tests/adapters/__init__.py
```

### 6.2 创建 `tests/adapters/test_agent_adapter.py`

```python
"""AgentAdapter 单元测试。"""
from __future__ import annotations

import pytest

from agently_skills_runtime.protocol.capability import (
    CapabilityKind, CapabilitySpec, CapabilityResult, CapabilityStatus,
)
from agently_skills_runtime.protocol.agent import AgentSpec, AgentIOSchema
from agently_skills_runtime.protocol.skill import SkillSpec
from agently_skills_runtime.protocol.context import ExecutionContext
from agently_skills_runtime.runtime.registry import CapabilityRegistry
from agently_skills_runtime.adapters.agent_adapter import AgentAdapter


class FakeRuntime:
    """模拟 CapabilityRuntime 的最小接口。"""
    def __init__(self):
        self.registry = CapabilityRegistry()


async def mock_runner(task: str, *, initial_history=None) -> str:
    """Mock runner 直接返回 task 文本。"""
    return f"output:{task[:50]}"


@pytest.mark.asyncio
async def test_basic_execution():
    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
    )
    adapter = AgentAdapter(runner=mock_runner)
    rt = FakeRuntime()
    ctx = ExecutionContext(run_id="r1")

    result = await adapter.execute(spec=spec, input={"task": "hello"}, context=ctx, runtime=rt)

    assert result.status == CapabilityStatus.SUCCESS
    assert "output:" in result.output
    assert "hello" in result.output


@pytest.mark.asyncio
async def test_no_runner():
    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
    )
    adapter = AgentAdapter(runner=None)
    rt = FakeRuntime()
    ctx = ExecutionContext(run_id="r1")

    result = await adapter.execute(spec=spec, input={}, context=ctx, runtime=rt)

    assert result.status == CapabilityStatus.FAILED
    assert "no runner" in result.error.lower()


@pytest.mark.asyncio
async def test_prompt_template():
    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
        prompt_template="设计角色：{name}",
    )
    
    captured = {}
    async def capture_runner(task, *, initial_history=None):
        captured["task"] = task
        return "result"
    
    adapter = AgentAdapter(runner=capture_runner)
    rt = FakeRuntime()
    ctx = ExecutionContext(run_id="r1")

    await adapter.execute(spec=spec, input={"name": "Alice"}, context=ctx, runtime=rt)
    assert "设计角色：Alice" in captured["task"]


@pytest.mark.asyncio
async def test_system_prompt_as_initial_history():
    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
        system_prompt="你是专家",
    )

    captured = {}
    async def capture_runner(task, *, initial_history=None):
        captured["initial_history"] = initial_history
        return "result"

    adapter = AgentAdapter(runner=capture_runner)
    rt = FakeRuntime()
    ctx = ExecutionContext(run_id="r1")

    await adapter.execute(spec=spec, input={"task": "x"}, context=ctx, runtime=rt)
    assert captured["initial_history"][0]["role"] == "system"
    assert captured["initial_history"][0]["content"] == "你是专家"


@pytest.mark.asyncio
async def test_skill_injection():
    skill = SkillSpec(
        base=CapabilitySpec(id="sk1", kind=CapabilityKind.SKILL, name="模板"),
        source="这是模板内容",
        source_type="inline",
    )
    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
        skills=["sk1"],
    )

    captured = {}
    async def capture_runner(task, *, initial_history=None):
        captured["task"] = task
        return "result"

    adapter = AgentAdapter(runner=capture_runner)
    rt = FakeRuntime()
    rt.registry.register(skill)
    ctx = ExecutionContext(run_id="r1")

    await adapter.execute(spec=spec, input={"task": "x"}, context=ctx, runtime=rt)
    assert "模板内容" in captured["task"]
    assert "[Skill: 模板]" in captured["task"]


@pytest.mark.asyncio
async def test_inject_to_skill():
    """测试 SkillSpec.inject_to 自动注入。"""
    skill = SkillSpec(
        base=CapabilitySpec(id="sk2", kind=CapabilityKind.SKILL, name="自动注入"),
        source="自动注入的内容",
        source_type="inline",
        inject_to=["A"],
    )
    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
        skills=[],  # 没有主动声明
    )

    captured = {}
    async def capture_runner(task, *, initial_history=None):
        captured["task"] = task
        return "result"

    adapter = AgentAdapter(runner=capture_runner)
    rt = FakeRuntime()
    rt.registry.register(skill)
    ctx = ExecutionContext(run_id="r1")

    await adapter.execute(spec=spec, input={"task": "x"}, context=ctx, runtime=rt)
    assert "自动注入的内容" in captured["task"]


@pytest.mark.asyncio
async def test_output_schema_hint():
    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
        output_schema=AgentIOSchema(fields={"score": "int", "analysis": "str"}),
    )

    captured = {}
    async def capture_runner(task, *, initial_history=None):
        captured["task"] = task
        return "result"

    adapter = AgentAdapter(runner=capture_runner)
    rt = FakeRuntime()
    ctx = ExecutionContext(run_id="r1")

    await adapter.execute(spec=spec, input={"task": "x"}, context=ctx, runtime=rt)
    assert "JSON" in captured["task"]
    assert "score" in captured["task"]


@pytest.mark.asyncio
async def test_runner_exception():
    async def bad_runner(task, *, initial_history=None):
        raise ConnectionError("network error")

    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
    )
    adapter = AgentAdapter(runner=bad_runner)
    rt = FakeRuntime()
    ctx = ExecutionContext(run_id="r1")

    result = await adapter.execute(spec=spec, input={}, context=ctx, runtime=rt)
    assert result.status == CapabilityStatus.FAILED
    assert "network error" in result.error


@pytest.mark.asyncio
async def test_wrap_node_result_v2():
    """测试兼容 NodeResultV2 格式。"""
    class FakeNodeReport:
        status = "success"
        reason = None
        meta = {"final_output": "the output"}

    class FakeNodeResult:
        final_output = "the output"
        node_report = FakeNodeReport()

    async def nr_runner(task, *, initial_history=None):
        return FakeNodeResult()

    spec = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
    )
    adapter = AgentAdapter(runner=nr_runner)
    rt = FakeRuntime()
    ctx = ExecutionContext(run_id="r1")

    result = await adapter.execute(spec=spec, input={}, context=ctx, runtime=rt)
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output == "the output"
    assert result.report is not None
```

### 6.3 创建 `tests/adapters/test_workflow_adapter.py`

```python
"""WorkflowAdapter 单元测试。"""
from __future__ import annotations

import pytest

from agently_skills_runtime.protocol.capability import (
    CapabilityKind, CapabilitySpec, CapabilityRef, CapabilityResult, CapabilityStatus,
)
from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.protocol.workflow import (
    WorkflowSpec, Step, LoopStep, ParallelStep, ConditionalStep, InputMapping,
)
from agently_skills_runtime.runtime.engine import CapabilityRuntime, RuntimeConfig
from agently_skills_runtime.adapters.workflow_adapter import WorkflowAdapter


class EchoAdapter:
    """Mock adapter：输出 = 输入 + spec_id。"""

    async def execute(self, *, spec, input, context, runtime):
        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output={**input, "__agent__": spec.base.id},
        )


class CounterAdapter:
    """Mock adapter：记录调用次数并输出 index。"""

    def __init__(self):
        self.call_count = 0

    async def execute(self, *, spec, input, context, runtime):
        self.call_count += 1
        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output={"index": self.call_count, **input},
        )


def _make_agent(id: str) -> AgentSpec:
    return AgentSpec(
        base=CapabilitySpec(id=id, kind=CapabilityKind.AGENT, name=id),
    )


def _build_runtime(agents, adapter=None):
    rt = CapabilityRuntime(config=RuntimeConfig(max_depth=10))
    a = adapter or EchoAdapter()
    rt.set_adapter(CapabilityKind.AGENT, a)
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    for agent in agents:
        rt.register(agent)
    return rt


@pytest.mark.asyncio
async def test_sequential_steps():
    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-1", kind=CapabilityKind.WORKFLOW, name="seq"),
        steps=[
            Step(id="s1", capability=CapabilityRef(id="A")),
            Step(
                id="s2",
                capability=CapabilityRef(id="B"),
                input_mappings=[InputMapping(source="step.s1.__agent__", target_field="from")],
            ),
        ],
    )
    rt = _build_runtime([_make_agent("A"), _make_agent("B")])
    rt.register(wf)

    result = await rt.run("WF-1", input={"data": "hello"})
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output["s1"]["__agent__"] == "A"
    assert result.output["s2"]["from"] == "A"


@pytest.mark.asyncio
async def test_loop_step():
    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-L", kind=CapabilityKind.WORKFLOW, name="loop"),
        steps=[
            Step(id="plan", capability=CapabilityRef(id="PLANNER")),
            LoopStep(
                id="loop",
                capability=CapabilityRef(id="WORKER"),
                iterate_over="step.plan.items",
                item_input_mappings=[
                    InputMapping(source="item.name", target_field="name"),
                ],
                max_iterations=10,
            ),
        ],
    )

    class PlannerAdapter:
        async def execute(self, *, spec, input, context, runtime):
            if spec.base.id == "PLANNER":
                return CapabilityResult(
                    status=CapabilityStatus.SUCCESS,
                    output={"items": [{"name": "A"}, {"name": "B"}, {"name": "C"}]},
                )
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"processed": input.get("name", "?")},
            )

    rt = CapabilityRuntime(config=RuntimeConfig(max_depth=10))
    rt.set_adapter(CapabilityKind.AGENT, PlannerAdapter())
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    rt.register(_make_agent("PLANNER"))
    rt.register(_make_agent("WORKER"))
    rt.register(wf)

    result = await rt.run("WF-L")
    assert result.status == CapabilityStatus.SUCCESS
    loop_output = result.output["loop"]
    assert len(loop_output) == 3


@pytest.mark.asyncio
async def test_parallel_step():
    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-P", kind=CapabilityKind.WORKFLOW, name="parallel"),
        steps=[
            ParallelStep(
                id="p1",
                branches=[
                    Step(id="b1", capability=CapabilityRef(id="A")),
                    Step(id="b2", capability=CapabilityRef(id="B")),
                ],
                join_strategy="all_success",
            ),
        ],
    )

    rt = _build_runtime([_make_agent("A"), _make_agent("B")])
    rt.register(wf)

    result = await rt.run("WF-P", input={"data": "test"})
    assert result.status == CapabilityStatus.SUCCESS
    assert len(result.output["p1"]) == 2


@pytest.mark.asyncio
async def test_conditional_step():
    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-C", kind=CapabilityKind.WORKFLOW, name="cond"),
        steps=[
            Step(id="classify", capability=CapabilityRef(id="CLASSIFIER")),
            ConditionalStep(
                id="branch",
                condition_source="step.classify.category",
                branches={
                    "romance": Step(id="rom", capability=CapabilityRef(id="ROMANCE")),
                    "action": Step(id="act", capability=CapabilityRef(id="ACTION")),
                },
            ),
        ],
    )

    class ClassifyAdapter:
        async def execute(self, *, spec, input, context, runtime):
            if spec.base.id == "CLASSIFIER":
                return CapabilityResult(
                    status=CapabilityStatus.SUCCESS,
                    output={"category": "romance"},
                )
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"genre": spec.base.id},
            )

    rt = CapabilityRuntime(config=RuntimeConfig(max_depth=10))
    rt.set_adapter(CapabilityKind.AGENT, ClassifyAdapter())
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    for id in ["CLASSIFIER", "ROMANCE", "ACTION"]:
        rt.register(_make_agent(id))
    rt.register(wf)

    result = await rt.run("WF-C")
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output["branch"]["genre"] == "ROMANCE"


@pytest.mark.asyncio
async def test_output_mappings():
    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-O", kind=CapabilityKind.WORKFLOW, name="output"),
        steps=[
            Step(id="s1", capability=CapabilityRef(id="A")),
        ],
        output_mappings=[
            InputMapping(source="step.s1.__agent__", target_field="agent_name"),
        ],
    )

    rt = _build_runtime([_make_agent("A")])
    rt.register(wf)

    result = await rt.run("WF-O", input={"x": 1})
    assert result.output == {"agent_name": "A"}


@pytest.mark.asyncio
async def test_step_failure_aborts_workflow():
    class FailOnB:
        async def execute(self, *, spec, input, context, runtime):
            if spec.base.id == "B":
                return CapabilityResult(status=CapabilityStatus.FAILED, error="B failed")
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output="ok")

    wf = WorkflowSpec(
        base=CapabilitySpec(id="WF-F", kind=CapabilityKind.WORKFLOW, name="fail"),
        steps=[
            Step(id="s1", capability=CapabilityRef(id="A")),
            Step(id="s2", capability=CapabilityRef(id="B")),
            Step(id="s3", capability=CapabilityRef(id="C")),  # 不应执行
        ],
    )

    rt = CapabilityRuntime()
    rt.set_adapter(CapabilityKind.AGENT, FailOnB())
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    for id in ["A", "B", "C"]:
        rt.register(_make_agent(id))
    rt.register(wf)

    result = await rt.run("WF-F")
    assert result.status == CapabilityStatus.FAILED
    assert "B failed" in result.error
```

### 6.4 创建 `tests/adapters/test_skill_adapter.py`

```python
"""SkillAdapter 单元测试。"""
from __future__ import annotations

import os
import pytest

from agently_skills_runtime.protocol.capability import (
    CapabilityKind, CapabilitySpec, CapabilityRef, CapabilityResult, CapabilityStatus,
)
from agently_skills_runtime.protocol.skill import SkillSpec, SkillDispatchRule
from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.protocol.context import ExecutionContext
from agently_skills_runtime.runtime.engine import CapabilityRuntime, RuntimeConfig
from agently_skills_runtime.adapters.skill_adapter import SkillAdapter


@pytest.mark.asyncio
async def test_inline_skill():
    spec = SkillSpec(
        base=CapabilitySpec(id="s1", kind=CapabilityKind.SKILL, name="inline"),
        source="这是内联内容",
        source_type="inline",
    )
    adapter = SkillAdapter()
    rt = CapabilityRuntime()
    ctx = ExecutionContext(run_id="r1")

    result = await adapter.execute(spec=spec, input={}, context=ctx, runtime=rt)
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output == "这是内联内容"


@pytest.mark.asyncio
async def test_file_skill(tmp_path):
    skill_file = tmp_path / "skill.md"
    skill_file.write_text("# Skill 内容\n文件加载成功", encoding="utf-8")

    spec = SkillSpec(
        base=CapabilitySpec(id="s2", kind=CapabilityKind.SKILL, name="file"),
        source="skill.md",
        source_type="file",
    )
    adapter = SkillAdapter(workspace_root=str(tmp_path))
    rt = CapabilityRuntime()
    ctx = ExecutionContext(run_id="r1")

    result = await adapter.execute(spec=spec, input={}, context=ctx, runtime=rt)
    assert result.status == CapabilityStatus.SUCCESS
    assert "文件加载成功" in result.output


@pytest.mark.asyncio
async def test_uri_skill_blocked():
    spec = SkillSpec(
        base=CapabilitySpec(id="s3", kind=CapabilityKind.SKILL, name="uri"),
        source="https://example.com/skill",
        source_type="uri",
    )
    adapter = SkillAdapter()
    rt = CapabilityRuntime()
    ctx = ExecutionContext(run_id="r1")

    result = await adapter.execute(spec=spec, input={}, context=ctx, runtime=rt)
    assert result.status == CapabilityStatus.FAILED
    assert "allowlist" in result.error.lower() or "uri" in result.error.lower()


@pytest.mark.asyncio
async def test_dispatch_rule_triggered():
    """dispatch_rule 触发时调用目标能力。"""

    class EchoAdapter:
        async def execute(self, *, spec, input, context, runtime):
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output=f"dispatched to {spec.base.id}",
            )

    skill = SkillSpec(
        base=CapabilitySpec(id="s1", kind=CapabilityKind.SKILL, name="s1"),
        source="content",
        source_type="inline",
        dispatch_rules=[
            SkillDispatchRule(
                condition="trigger_flag",
                target=CapabilityRef(id="A"),
            ),
        ],
    )
    agent = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
    )

    rt = CapabilityRuntime()
    rt.set_adapter(CapabilityKind.AGENT, EchoAdapter())
    rt.set_adapter(CapabilityKind.SKILL, SkillAdapter())
    rt.registry.register(skill)
    rt.registry.register(agent)

    # trigger_flag 为 True
    ctx = ExecutionContext(run_id="r1", bag={"trigger_flag": True})
    result = await SkillAdapter().execute(spec=skill, input={}, context=ctx, runtime=rt)
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output == "content"
    assert len(result.metadata.get("dispatched", [])) == 1

    # trigger_flag 为 False
    ctx2 = ExecutionContext(run_id="r2", bag={"trigger_flag": False})
    result2 = await SkillAdapter().execute(spec=skill, input={}, context=ctx2, runtime=rt)
    assert result2.metadata.get("dispatched") is None or len(result2.metadata.get("dispatched", [])) == 0
```

---

## Step 7：创建场景测试

### 7.1 创建目录

```bash
mkdir -p tests/scenarios
touch tests/scenarios/__init__.py
```

### 7.2 创建 `tests/scenarios/test_wf001d_character_creation.py`

```python
"""场景测试：模拟 WF-001D 人物塑造子流程。"""
from __future__ import annotations

import pytest

from agently_skills_runtime.protocol.capability import (
    CapabilityKind, CapabilitySpec, CapabilityRef, CapabilityResult, CapabilityStatus,
)
from agently_skills_runtime.protocol.agent import AgentSpec, AgentIOSchema
from agently_skills_runtime.protocol.skill import SkillSpec
from agently_skills_runtime.protocol.workflow import (
    WorkflowSpec, Step, LoopStep, InputMapping,
)
from agently_skills_runtime.runtime.engine import CapabilityRuntime, RuntimeConfig
from agently_skills_runtime.adapters.workflow_adapter import WorkflowAdapter


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
                output={
                    "角色小传": f"{role}的完整人物设定...",
                    "外貌": "...",
                    "性格": "...",
                },
            )

        if agent_id == "MA-014":
            chars = input.get("角色小传列表", [])
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={
                    "关系图谱": f"共{len(chars)}个角色的关系...",
                    "核心冲突": "三角关系",
                },
            )

        if agent_id == "MA-015":
            char = input.get("角色小传", {})
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={
                    "视觉关键词": ["长发", "白裙", "月光下"],
                    "风格": "日系",
                },
            )

        return CapabilityResult(
            status=CapabilityStatus.FAILED,
            error=f"Unknown agent: {agent_id}",
        )


@pytest.mark.asyncio
async def test_wf001d_full_flow():
    """
    WF-001D: MA-013A → [MA-013×3] → MA-014 → [MA-015×3]
    验证完整的人物塑造子流程。
    """
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
                input_mappings=[
                    InputMapping(source="step.design", target_field="角色小传列表"),
                ],
            ),
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

    # 构建 Runtime
    rt = CapabilityRuntime(config=RuntimeConfig(max_depth=10))
    rt.set_adapter(CapabilityKind.AGENT, MockAgentAdapter())
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    for a in agents:
        rt.register(a)
    rt.register(wf)

    # 校验依赖
    missing = rt.validate()
    assert not missing, f"Missing: {missing}"

    # 执行
    result = await rt.run(
        "WF-001D",
        context_bag={"故事梗概": "霸道总裁爱上灰姑娘的故事"},
    )

    # 验证
    assert result.status == CapabilityStatus.SUCCESS
    assert result.duration_ms > 0

    output = result.output
    assert "角色小传列表" in output
    assert len(output["角色小传列表"]) == 3  # 3 个角色

    assert "角色关系图谱" in output
    assert "3个角色" in output["角色关系图谱"]["关系图谱"]

    assert "视觉关键词列表" in output
    assert len(output["视觉关键词列表"]) == 3
```

### 7.3 创建 `tests/scenarios/test_nested_workflow.py`

```python
"""场景测试：Workflow 嵌套 Workflow。"""
from __future__ import annotations

import pytest

from agently_skills_runtime.protocol.capability import (
    CapabilityKind, CapabilitySpec, CapabilityRef, CapabilityResult, CapabilityStatus,
)
from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.protocol.workflow import (
    WorkflowSpec, Step, InputMapping,
)
from agently_skills_runtime.runtime.engine import CapabilityRuntime, RuntimeConfig
from agently_skills_runtime.adapters.workflow_adapter import WorkflowAdapter


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
    agent = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
    )

    rt = CapabilityRuntime(config=RuntimeConfig(max_depth=10))
    rt.set_adapter(CapabilityKind.AGENT, SimpleAdapter())
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    rt.register_many([agent, inner, outer])

    result = await rt.run("WF-outer")
    assert result.status == CapabilityStatus.SUCCESS


@pytest.mark.asyncio
async def test_deep_nesting_hits_limit():
    """深层嵌套超过 max_depth。"""
    # 创建 5 层嵌套的 workflow，每层调用下一层
    specs = []
    for i in range(5):
        next_id = f"WF-{i+1}" if i < 4 else "A"
        wf = WorkflowSpec(
            base=CapabilitySpec(id=f"WF-{i}", kind=CapabilityKind.WORKFLOW, name=f"wf-{i}"),
            steps=[Step(id="s1", capability=CapabilityRef(id=next_id))],
        )
        specs.append(wf)
    specs.append(AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
    ))

    rt = CapabilityRuntime(config=RuntimeConfig(max_depth=3))
    rt.set_adapter(CapabilityKind.AGENT, SimpleAdapter())
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    rt.register_many(specs)

    result = await rt.run("WF-0")
    assert result.status == CapabilityStatus.FAILED
    assert "recursion" in result.error.lower() or "depth" in result.error.lower()
```

---

## Step 8：更新 pyproject.toml 版本

将版本号更新为 `0.4.0`：

```toml
version = "0.4.0"
```

---

## Step 9：验证

### 9.1 安装

```bash
pip install -e ".[dev]"
```

### 9.2 运行全量测试

```bash
python -m pytest -v
```

### 9.3 验证完整导入链

```bash
python -c "
from agently_skills_runtime import (
    # Protocol
    CapabilityKind, CapabilitySpec, CapabilityResult, AgentSpec, WorkflowSpec,
    Step, LoopStep, ParallelStep, ConditionalStep, InputMapping,
    ExecutionContext, SkillSpec,
    # Runtime
    CapabilityRuntime, RuntimeConfig, CapabilityRegistry,
    ExecutionGuards, LoopBreakerError, LoopController,
    # Adapters
    AgentAdapter, WorkflowAdapter, SkillAdapter,
    # Bridge (backward compat)
    AgentlySkillsRuntime, NodeReportV2, NodeResultV2,
)
print('All imports OK — v0.4.0 ready')
"
```

### 9.4 验证场景测试

```bash
python -m pytest tests/scenarios/ -v
```

---

## 完成标志

Phase 3 完成后，框架应具备完整的"声明→注册→校验→调度→执行→报告"管线：

- ✅ AgentAdapter：AgentSpec → Bridge → LLM（mock 验证）
- ✅ WorkflowAdapter：WorkflowSpec → Step/Loop/Parallel/Conditional 编排
- ✅ SkillAdapter：SkillSpec → 内容加载 + dispatch_rules
- ✅ WF-001D 场景测试通过（人物塑造子流程：4 步含 2 个循环）
- ✅ 嵌套 Workflow 场景测试通过
- ✅ 所有已有测试不受影响
- ✅ 版本号 0.4.0
- ✅ 可以直接进入业务层集成

---

## 后续（Phase 4，非本次范围）

Phase 4 将涉及：
1. 真实上游集成测试（需要 LLM API key）
2. 业务层 MA-001~027 的 AgentSpec 定义
3. 业务层 WF-001~004 的 WorkflowSpec 定义
4. TriggerFlow 顶层编排集成（路径 B）
5. 存储架构（制品归档、状态持久化）
