# Cheatsheet：最短闭环（以统一 Runtime 为真相源）

> 面向：编码智能体 / 维护者  
> 目标：用最少上下文跑通 **Protocol（声明）→ Runtime（执行）→ Report（证据链）** 的最小闭环。  
> 注意：本仓 **不** 维护 TriggerFlow 作为 SDK Agent tool 的桥接（`triggerflow_run_flow` 已搁置归档）；推荐使用 TriggerFlow 顶层编排多个 `Runtime.run()`。

## 0) 你只需要记住三件事

1. **Protocol**：声明 Agent/Workflow（dataclass/Enum），不依赖上游
2. **Runtime**：唯一执行入口 `Runtime.run()` / `Runtime.run_stream()`
3. **Report**：桥接模式下会聚合上游事件，产出 `NodeReport`（系统级证据链）

## 1) 10 行代码最小闭环（mock，离线可跑）

```python
import asyncio
from capability_runtime import Runtime, RuntimeConfig, CapabilitySpec, CapabilityKind, AgentSpec
def handler(spec, input, context=None): return {"echo": input}
rt = Runtime(RuntimeConfig(mode="mock", mock_handler=handler))
rt.register(AgentSpec(base=CapabilitySpec(id="echo", kind=CapabilityKind.AGENT, name="Echo")))
assert rt.validate() == []
res = asyncio.run(rt.run("echo", input={"x": 1}))
print(res.status.value)
print(res.output)
print(res.node_report)
```

## 2) import 速查（只列公共 API）

```python
# === 唯一入口 ===
from capability_runtime import Runtime, RuntimeConfig, CustomTool

# === 协议（声明能力用）===
from capability_runtime import (
    CapabilitySpec, CapabilityKind, CapabilityRef,
    CapabilityResult, CapabilityStatus,
    AgentSpec, AgentIOSchema,
    WorkflowSpec, Step, LoopStep, ParallelStep, ConditionalStep, InputMapping,
    ExecutionContext,
)

# === 报告（消费结果用）===
from capability_runtime import NodeReport, NodeResult

# === 错误 ===
from capability_runtime import (
    RuntimeFrameworkError,
    CapabilityNotFoundError,
    AdapterNotFoundError,
)
```

## 3) Runtime 两个执行入口的语义差异

- `await Runtime.run(capability_id, input=..., context=...)`
  - 返回：`CapabilityResult`（终态）
  - 适用：业务代码“只要结果”，不需要中间事件
- `async for x in Runtime.run_stream(...):`
  - Agent 路径先产出：上游 `AgentEvent`（bridge/sdk_native）
  - Workflow 路径先产出：轻量事件（`workflow.started`、`workflow.step.started/finished`、`workflow.finished`）
  - 最后产出：`CapabilityResult`（终态）
  - 适用：宿主需要把事件写入日志、做可观测、或构建额外审计链

## 4) 常见错误（最短排查路径）

- 忘记 `validate()`：`Capability not found: ...`（先注册缺失能力再跑）
- 误以为本仓还内置“skills 原语/注入机制”：本仓只暴露 Agent/Workflow；skills（catalog/mention/sources/preflight/tools/approvals/WAL）以 `skills_runtime` 为真相源
- 想在本仓走 “TriggerFlow tool”：已按规格搁置归档；应在业务侧用 TriggerFlow 顶层调用 `Runtime.run()`

## 5) invoke_capability（能力委托工具）要点

当你需要在一次 run 内实现 “Agent → 子 Agent/子 Workflow”（渐进式披露/能力委托）时，可由宿主注入自定义工具 `invoke_capability`（`RuntimeConfig.custom_tools`）。

关键约束（上游现实约束）：
- tool handler 为同步函数；不要在 handler 内直接 `await`
- 不要在运行中的 event loop 中直接调用 `asyncio.run()`
- 推荐使用“后台线程 + 独立 event loop”执行 `await Runtime.run(...)` 并等待返回

公共 API 入口（推荐）：`capability_runtime.make_invoke_capability_tool`。
