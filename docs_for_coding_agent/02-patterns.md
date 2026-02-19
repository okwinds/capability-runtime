# 6 种典型组合模式

本文从 `examples/01-08` 提炼可复用模式。每个模式都给出场景、数据流和可运行代码骨架。

## 模式 1：Agent 独立执行

场景：单次任务，输入直达 Agent，直接产出。

数据流：

```text
input -> Agent -> output
```

代码（提炼自 example 01）：

```python
from __future__ import annotations
import asyncio
from typing import Any
from agently_skills_runtime import AgentSpec, CapabilityKind, CapabilityResult, CapabilityRuntime, CapabilitySpec, CapabilityStatus, ExecutionContext, RuntimeConfig

class MockAdapter:
    async def execute(self, *, spec: AgentSpec, input: dict[str, Any], context: ExecutionContext, runtime: CapabilityRuntime) -> CapabilityResult:
        _ = context; _ = runtime; _ = spec
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"message": f"Hello, {input.get('name', 'world')}"})

async def main() -> None:
    rt = CapabilityRuntime(config=RuntimeConfig())
    rt.set_adapter(CapabilityKind.AGENT, MockAdapter())
    rt.register(AgentSpec(base=CapabilitySpec(id="agent.greeter", kind=CapabilityKind.AGENT, name="Greeter")))
    out = await rt.run("agent.greeter", input={"name": "Alice"})
    print(out.status.value, out.output)

if __name__ == "__main__":
    asyncio.run(main())
```

## 模式 2：Pipeline（顺序编排）

场景：线性处理链（A -> B -> C）。

数据流：

```text
input -> A -> B -> C -> output
```

InputMapping 要点：
- `context.x` 读初始输入
- `previous.x` 读上一步输出
- `step.a.x` 读指定步骤输出

代码（提炼自 example 02）：

```python
from __future__ import annotations
import asyncio
from agently_skills_runtime import AgentSpec, CapabilityKind, CapabilityRef, CapabilityResult, CapabilityRuntime, CapabilitySpec, CapabilityStatus, ExecutionContext, InputMapping, RuntimeConfig, Step, WorkflowAdapter, WorkflowSpec

class MockAdapter:
    async def execute(self, *, spec: AgentSpec, input, context: ExecutionContext, runtime: CapabilityRuntime) -> CapabilityResult:
        _ = context; _ = runtime
        if spec.base.id == "agent.a": return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"x": f"a({input['topic']})"})
        if spec.base.id == "agent.b": return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"y": f"b({input['x']})"})
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"z": f"c({input['y']})"})

async def main() -> None:
    rt = CapabilityRuntime(config=RuntimeConfig())
    rt.set_adapter(CapabilityKind.AGENT, MockAdapter())
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    rt.register_many([
        AgentSpec(base=CapabilitySpec(id="agent.a", kind=CapabilityKind.AGENT, name="A")),
        AgentSpec(base=CapabilitySpec(id="agent.b", kind=CapabilityKind.AGENT, name="B")),
        AgentSpec(base=CapabilitySpec(id="agent.c", kind=CapabilityKind.AGENT, name="C")),
        WorkflowSpec(base=CapabilitySpec(id="wf.pipeline", kind=CapabilityKind.WORKFLOW, name="Pipeline"), steps=[
            Step(id="a", capability=CapabilityRef(id="agent.a"), input_mappings=[InputMapping(source="context.topic", target_field="topic")]),
            Step(id="b", capability=CapabilityRef(id="agent.b"), input_mappings=[InputMapping(source="previous.x", target_field="x")]),
            Step(id="c", capability=CapabilityRef(id="agent.c"), input_mappings=[InputMapping(source="step.b.y", target_field="y")]),
        ]),
    ])
    print((await rt.run("wf.pipeline", input={"topic": "runtime"})).output)

if __name__ == "__main__":
    asyncio.run(main())
```

## 模式 3：Fan-out / Fan-in（循环编排）

场景：对列表元素逐个处理并收集结果。

数据流：

```text
input -> A -> [B x N] -> output(list)
```

LoopStep 要点：
- `iterate_over`：列表来源
- `item.x`：当前元素字段
- 输出为列表，后续可直接 `step.loop_id` 读取

代码（提炼自 example 03）：

```python
from __future__ import annotations
import asyncio
from agently_skills_runtime import AgentSpec, CapabilityKind, CapabilityRef, CapabilityResult, CapabilityRuntime, CapabilitySpec, CapabilityStatus, ExecutionContext, InputMapping, LoopStep, RuntimeConfig, Step, WorkflowAdapter, WorkflowSpec

class MockAdapter:
    async def execute(self, *, spec: AgentSpec, input, context: ExecutionContext, runtime: CapabilityRuntime) -> CapabilityResult:
        _ = context; _ = runtime
        if spec.base.id == "agent.list":
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"items": [{"name": "a"}, {"name": "b"}]})
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"processed": input["name"].upper()})

async def main() -> None:
    rt = CapabilityRuntime(config=RuntimeConfig())
    rt.set_adapter(CapabilityKind.AGENT, MockAdapter())
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    rt.register_many([
        AgentSpec(base=CapabilitySpec(id="agent.list", kind=CapabilityKind.AGENT, name="List")),
        AgentSpec(base=CapabilitySpec(id="agent.item", kind=CapabilityKind.AGENT, name="Item")),
        WorkflowSpec(base=CapabilitySpec(id="wf.loop", kind=CapabilityKind.WORKFLOW, name="Loop"), steps=[
            Step(id="gen", capability=CapabilityRef(id="agent.list")),
            LoopStep(id="loop", capability=CapabilityRef(id="agent.item"), iterate_over="step.gen.items", item_input_mappings=[InputMapping(source="item.name", target_field="name")]),
        ]),
    ])
    print((await rt.run("wf.loop")).output)

if __name__ == "__main__":
    asyncio.run(main())
```

## 模式 4：Scatter / Gather（并行编排）

场景：同源输入，多视角并行分析，最后汇总。

数据流：

```text
input -> [A | B | C] -> D -> output
```

ParallelStep 要点：
- `branches` 定义并行分支
- `join_strategy` 常用 `all_success`

代码（提炼自 example 04）：

```python
from __future__ import annotations
import asyncio
from agently_skills_runtime import AgentSpec, CapabilityKind, CapabilityRef, CapabilityResult, CapabilityRuntime, CapabilitySpec, CapabilityStatus, ExecutionContext, InputMapping, ParallelStep, RuntimeConfig, Step, WorkflowAdapter, WorkflowSpec

class MockAdapter:
    async def execute(self, *, spec: AgentSpec, input, context: ExecutionContext, runtime: CapabilityRuntime) -> CapabilityResult:
        _ = context; _ = runtime
        if spec.base.id.startswith("agent.view"):
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"analysis": f"{spec.base.id}:{input['data']}"})
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"report": " | ".join([input["a"], input["b"], input["c"]])})

async def main() -> None:
    rt = CapabilityRuntime(config=RuntimeConfig())
    rt.set_adapter(CapabilityKind.AGENT, MockAdapter())
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    rt.register_many([
        AgentSpec(base=CapabilitySpec(id="agent.view.a", kind=CapabilityKind.AGENT, name="A")),
        AgentSpec(base=CapabilitySpec(id="agent.view.b", kind=CapabilityKind.AGENT, name="B")),
        AgentSpec(base=CapabilitySpec(id="agent.view.c", kind=CapabilityKind.AGENT, name="C")),
        AgentSpec(base=CapabilitySpec(id="agent.merge", kind=CapabilityKind.AGENT, name="Merge")),
        WorkflowSpec(base=CapabilitySpec(id="wf.parallel", kind=CapabilityKind.WORKFLOW, name="Parallel"), steps=[
            ParallelStep(id="parallel", branches=[
                Step(id="a", capability=CapabilityRef(id="agent.view.a"), input_mappings=[InputMapping(source="context.data", target_field="data")]),
                Step(id="b", capability=CapabilityRef(id="agent.view.b"), input_mappings=[InputMapping(source="context.data", target_field="data")]),
                Step(id="c", capability=CapabilityRef(id="agent.view.c"), input_mappings=[InputMapping(source="context.data", target_field="data")]),
            ], join_strategy="all_success"),
            Step(id="merge", capability=CapabilityRef(id="agent.merge"), input_mappings=[
                InputMapping(source="step.a.analysis", target_field="a"),
                InputMapping(source="step.b.analysis", target_field="b"),
                InputMapping(source="step.c.analysis", target_field="c"),
            ]),
        ]),
    ])
    print((await rt.run("wf.parallel", input={"data": "feedback"})).output)

if __name__ == "__main__":
    asyncio.run(main())
```

## 模式 5：Router（条件分支）

场景：先分类，再路由到对应处理链。

数据流：

```text
input -> Classifier -> {positive: A, negative: B, default: C}
```

ConditionalStep 要点：
- `condition_source` 提供分支键
- `branches` + `default` 控制路由

代码（提炼自 example 05）：

```python
from __future__ import annotations
import asyncio
from agently_skills_runtime import AgentSpec, CapabilityKind, CapabilityRef, CapabilityResult, CapabilityRuntime, CapabilitySpec, CapabilityStatus, ConditionalStep, ExecutionContext, InputMapping, RuntimeConfig, Step, WorkflowAdapter, WorkflowSpec

class MockAdapter:
    async def execute(self, *, spec: AgentSpec, input, context: ExecutionContext, runtime: CapabilityRuntime) -> CapabilityResult:
        _ = context; _ = runtime
        if spec.base.id == "agent.classify":
            text = str(input.get("text", "")).lower()
            cat = "positive" if "good" in text else ("negative" if "bad" in text else "neutral")
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"category": cat})
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"handler": spec.base.id})

async def main() -> None:
    rt = CapabilityRuntime(config=RuntimeConfig())
    rt.set_adapter(CapabilityKind.AGENT, MockAdapter())
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    rt.register_many([
        AgentSpec(base=CapabilitySpec(id="agent.classify", kind=CapabilityKind.AGENT, name="Classifier")),
        AgentSpec(base=CapabilitySpec(id="agent.pos", kind=CapabilityKind.AGENT, name="Positive")),
        AgentSpec(base=CapabilitySpec(id="agent.neg", kind=CapabilityKind.AGENT, name="Negative")),
        AgentSpec(base=CapabilitySpec(id="agent.neu", kind=CapabilityKind.AGENT, name="Neutral")),
        WorkflowSpec(base=CapabilitySpec(id="wf.router", kind=CapabilityKind.WORKFLOW, name="Router"), steps=[
            Step(id="classify", capability=CapabilityRef(id="agent.classify"), input_mappings=[InputMapping(source="context.text", target_field="text")]),
            ConditionalStep(id="route", condition_source="step.classify.category", branches={
                "positive": Step(id="pos", capability=CapabilityRef(id="agent.pos")),
                "negative": Step(id="neg", capability=CapabilityRef(id="agent.neg")),
            }, default=Step(id="neu", capability=CapabilityRef(id="agent.neu"))),
        ]),
    ])
    print((await rt.run("wf.router", input={"text": "good release"})).output)

if __name__ == "__main__":
    asyncio.run(main())
```

## 模式 6：Hierarchical（嵌套编排）

场景：主流程调用子流程，形成分层编排。

数据流：

```text
WF-outer -> [A -> WF-inner -> [B -> C] -> D]
```

要点：
- `Workflow` 的 step 可引用另一个 `Workflow`
- 通过 `RuntimeConfig(max_depth=...)` 防递归失控

代码（提炼自 example 08）：

```python
from __future__ import annotations
import asyncio
from agently_skills_runtime import AgentSpec, CapabilityKind, CapabilityRef, CapabilityResult, CapabilityRuntime, CapabilitySpec, CapabilityStatus, ExecutionContext, InputMapping, RuntimeConfig, Step, WorkflowAdapter, WorkflowSpec

class MockAdapter:
    async def execute(self, *, spec: AgentSpec, input, context: ExecutionContext, runtime: CapabilityRuntime) -> CapabilityResult:
        _ = context; _ = runtime
        return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"text": f"{spec.base.id}:{input}"})

async def main() -> None:
    rt = CapabilityRuntime(config=RuntimeConfig(max_depth=10))
    rt.set_adapter(CapabilityKind.AGENT, MockAdapter())
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    rt.register_many([
        AgentSpec(base=CapabilitySpec(id="agent.draft", kind=CapabilityKind.AGENT, name="Draft")),
        AgentSpec(base=CapabilitySpec(id="agent.polish", kind=CapabilityKind.AGENT, name="Polish")),
        WorkflowSpec(base=CapabilitySpec(id="wf.inner", kind=CapabilityKind.WORKFLOW, name="Inner"), steps=[
            Step(id="draft", capability=CapabilityRef(id="agent.draft"), input_mappings=[InputMapping(source="context.topic", target_field="topic")]),
            Step(id="polish", capability=CapabilityRef(id="agent.polish"), input_mappings=[InputMapping(source="step.draft.text", target_field="text")]),
        ]),
        WorkflowSpec(base=CapabilitySpec(id="wf.outer", kind=CapabilityKind.WORKFLOW, name="Outer"), steps=[
            Step(id="inner", capability=CapabilityRef(id="wf.inner"), input_mappings=[InputMapping(source="context.topic", target_field="topic")]),
            Step(id="publish", capability=CapabilityRef(id="agent.polish"), input_mappings=[InputMapping(source="step.inner.polish", target_field="text")]),
        ]),
    ])
    print((await rt.run("wf.outer", input={"topic": "release"})).output)

if __name__ == "__main__":
    asyncio.run(main())
```

## 模式组合

以上模式可以自由组合。

常见组合：
1. Pipeline 的某一步嵌入 Fan-out（LoopStep）
2. Fan-out 的循环体内再做 Router（ConditionalStep）
3. 主流程通过 Hierarchical 调用可复用子流程

`examples/09_full_scenario_mock` 就是典型组合：
- 主干是 Pipeline
- 中段通过 LoopStep 做 Fan-out
- 末端收敛为统一输出契约（`output_mappings`）
