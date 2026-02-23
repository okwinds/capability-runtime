# agently-skills-runtime Cheatsheet

> 面向：编码智能体（Codex CLI / Claude Code / 其他）  
> 目标：用**最少上下文**跑通“声明 → 注册 → 校验 → 执行 / 编排”的最小闭环。  
> 前置：已阅读 `archive/instructcontext/5-true-CODEX_CONTEXT_BRIEF.md`（桥接主线 / 协议独立 / 业务无关）。

## 0) 核心共识

- 能力原语收敛：本仓库对外的 Protocol 原语仅 **Agent / Workflow**（共享 `CapabilitySpec`）
- skills 真相源：skills 的发现/mention/sources/preflight/tools/approvals/WAL 全部以 `skills-runtime-sdk-python`（模块 `agent_sdk`）为准
- 互嵌可组合：Workflow step 可调用 Agent/Workflow；顶层编排入口默认是 Agently TriggerFlow（生态入口）
- 标准流程：声明 → 注册 → 校验 → 执行（`register` → `validate` → `run`）
- 协议独立：`protocol/` 层只放 dataclass/Enum/类型声明，不依赖上游（便于审计与回归）
- 委托执行：框架负责组织与调度；真实执行由 Adapter 委托给上游或 mock（示例默认离线 mock）
- 可审计：每次执行返回 `CapabilityResult`，并携带 `ExecutionContext` 调用链信息

## 1) 最短路径：10 行代码跑通第一个 Agent

> 说明：这是“能复制粘贴就能跑”的最小闭环（使用 mock adapter）。  
> 约束：示例不依赖真实 LLM、不需要网络；仅依赖本仓源码可导入。

```python
from __future__ import annotations
import asyncio
from agently_skills_runtime.protocol.capability import CapabilityKind, CapabilitySpec, CapabilityResult, CapabilityStatus
from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.runtime.engine import CapabilityRuntime, RuntimeConfig
class A: async def execute(self, *, spec, input, context, runtime): return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"reply": f"hi {input.get('name','world')}", "id": spec.base.id})
async def main():
    rt=CapabilityRuntime(config=RuntimeConfig()); rt.set_adapter(CapabilityKind.AGENT, A()); rt.register(AgentSpec(base=CapabilitySpec(id="greeter", kind=CapabilityKind.AGENT, name="Greeter", description="demo"))); assert not rt.validate()
    r=await rt.run("greeter", input={"name":"Alice"}); assert r.status==CapabilityStatus.SUCCESS; print(r.status.value, r.output)
asyncio.run(main())
```

## 2) 核心 import 速查

> 只列“公共 API 常用面”。更细粒度类型请在 `src/agently_skills_runtime/` 内检索对应模块。

### Protocol（纯类型声明，零上游依赖）

```python
from agently_skills_runtime.protocol.capability import (
    CapabilitySpec, CapabilityKind, CapabilityRef,
    CapabilityResult, CapabilityStatus,
)
from agently_skills_runtime.protocol.agent import AgentSpec, AgentIOSchema
from agently_skills_runtime.protocol.workflow import (
    WorkflowSpec,
    Step, LoopStep, ParallelStep, ConditionalStep,
    InputMapping,
)
from agently_skills_runtime.protocol.context import ExecutionContext, RecursionLimitError
```

### Runtime（注册 + 执行引擎 + 护栏）

```python
from agently_skills_runtime.runtime.engine import CapabilityRuntime, RuntimeConfig, AdapterProtocol
```

### Adapters（把“声明”落到“可执行”）

```python
from agently_skills_runtime.adapters.agent_adapter import AgentAdapter
from agently_skills_runtime.adapters.workflow_adapter import WorkflowAdapter
```

### Reporting（证据链/控制面，可选）

```python
from agently_skills_runtime.types import NodeReportV2, NodeResultV2
from agently_skills_runtime.reporting.node_report import NodeReportBuilder
```

- `NodeResultV2`：一次运行的“对外返回值”（data plane + control plane）
- `NodeReportV2`：控制面强结构（tool_calls / approvals / events_path 等证据链）
- `NodeReportBuilder`：把上游 SDK 的事件流聚合为 NodeReport（适合做审计/回归护栏）

## 3) 五种 Workflow 编排模式

> 目标：记住“Step 类型 + InputMapping 数据流”就能写出 80% 的编排。

### 顺序执行（`Step`）

```python
wf = WorkflowSpec(
  base=CapabilitySpec(id="wf", kind=CapabilityKind.WORKFLOW, name="wf", description=""),
  steps=[Step(id="a", capability=CapabilityRef(id="agent_a")), Step(id="b", capability=CapabilityRef(id="agent_b"))],
)
```

一句话：按 `steps` 声明顺序依次执行；每步输出存入 `context.step_outputs[step_id]`。

补充：Workflow 默认输出行为（便于快速排查“我到底拿到了什么”）

- 若 `WorkflowSpec.output_mappings` 为空：最终输出是 `context.step_outputs` 的拷贝（字典）
- 若 `output_mappings` 非空：最终输出由 `output_mappings` 指定字段构造（字典）

### 循环编排（`LoopStep`）

```python
LoopStep(
  id="loop", capability=CapabilityRef(id="item_processor"),
  iterate_over="step.generate.items", item_input_mappings=[InputMapping(source="item.name", target_field="item_name")],
)
```

一句话：`iterate_over` 必须解析成 `list`；循环内用 `item` / `item.{key}` 读取当前元素。

### 并行编排（`ParallelStep`）

```python
ParallelStep(
  id="par",
  branches=[Step(id="alpha", capability=CapabilityRef(id="analyzer_alpha")), Step(id="beta", capability=CapabilityRef(id="analyzer_beta"))],
  join_strategy="all_success",
)
```

一句话：`branches` 中每个分支都是一个“可执行的 step”；输出可通过 `step.{branch_id}` 被后续步骤引用。

### 条件分支（`ConditionalStep`）

```python
ConditionalStep(
  id="route", condition_source="step.classify.category",
  branches={"positive": Step(id="pos", capability=CapabilityRef(id="positive_handler"))},
  default=Step(id="default", capability=CapabilityRef(id="neutral_handler")),
)
```

一句话：`condition_source` 解析为字符串后做分支选择；无匹配时走 `default`（若不存在则失败）。

### 嵌套 Workflow

```python
Step(id="subflow", capability=CapabilityRef(id="WF-SUB"))  # WF-SUB 本身是一个 WorkflowSpec
```

一句话：Workflow 只是“能力”；嵌套等价于在 step 中调用另一个 capability id。

## 4) InputMapping 6 种 source 前缀

| 前缀 | 语义 | 示例（source） |
|---|---|---|
| `context.{key}` | 读取 context bag | `context.topic` |
| `previous.{key}` | 读取“上一步输出”的字段 | `previous.best_idea` |
| `step.{step_id}.{key}` | 读取指定步骤输出字段 | `step.generate.items` |
| `step.{step_id}` | 读取指定步骤输出整体 | `step.generate` |
| `literal.{value}` | 字面量字符串 | `literal.default_mode` |
| `item` / `item.{key}` | 循环当前元素 | `item.name` |

> 注意：`ExecutionContext.resolve_mapping()` 设计为“找不到就返回 None（不抛异常）”。  
> 因此 prefix 拼写错误经常会表现为“静默得到 None”。

## 5) 安全护栏

### 5.1 递归深度（防无限嵌套）

- 配置点：`ExecutionContext.max_depth`（由 `RuntimeConfig.max_depth` 注入）
- 默认值：10
- 失败形态：`CapabilityResult(status=FAILED, metadata={"error_type": "recursion_limit"})`

配置示例：

```python
rt = CapabilityRuntime(config=RuntimeConfig(max_depth=5))
result = await rt.run("capability-id", input={}, max_depth=3)  # 单次覆盖
```

### 5.2 单步循环上限（防 LoopStep 失控）

- 配置点：`LoopStep.max_iterations`
- 默认值：100（协议层默认值）
- 失败形态：由 LoopController/Guards 返回 FAILED（见 `metadata.error_type`）

```python
LoopStep(id="loop", capability=CapabilityRef(id="x"), iterate_over="step.a.items", max_iterations=20)
```

补充：Loop 的失败策略（`LoopStep.fail_strategy`）

- `abort`：任一 item 失败 → 整个 LoopStep 失败（默认）
- `skip`：失败 item 被跳过（成功 item 继续）
- `collect`：把失败也作为结果的一部分收集（便于回归对比）

### 5.3 全局循环熔断（防多层循环叠加爆炸）

- 配置点：`RuntimeConfig.max_total_loop_iterations`
- 默认值：50000
- 触发形态：执行中止，返回 FAILED（`metadata.error_type = "loop_breaker"`）

```python
rt = CapabilityRuntime(config=RuntimeConfig(max_total_loop_iterations=2000))
```

## 6) 常见错误

- ❌ 忘记 `validate()` → 运行时 `Capability not found: 'xxx'`
- ❌ 只注册了 Spec、没注入 Adapter → `No adapter registered for kind: agent/workflow/skill`
- ❌ `LoopStep.iterate_over` 指向非列表 → `expected list`（LoopStep 直接失败）
- ❌ `InputMapping.source` 前缀拼写错误 → `resolve_mapping()` 返回 None（后续步骤“莫名其妙”）
- ❌ 分支条件无匹配且没写 `default` → `ConditionalStep 'x': no branch ... and no default`
- ❌ 并行 join 策略选错：
  - `all_success`：任何分支失败都会导致整步失败
  - `any_success`：必须至少一个成功，否则失败
