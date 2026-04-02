<div align="center">

[English](cheatsheet.md) | [中文](cheatsheet.zh-CN.md)

</div>

# Cheatsheet：最短执行闭环

## 你只需要记住三件事

1. 用 `AgentSpec` / `WorkflowSpec` 声明能力
2. 用 `Runtime.run()` / `Runtime.run_stream()` 执行
3. 用 `NodeReport` / `HostRunSnapshot` 读取结构化证据

## 最小离线示例

```python
import asyncio

from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec, Runtime, RuntimeConfig


def handler(spec, input, context=None):
    return {"echo": input}


runtime = Runtime(RuntimeConfig(mode="mock", mock_handler=handler))
runtime.register(
    AgentSpec(
        base=CapabilitySpec(
            id="echo",
            kind=CapabilityKind.AGENT,
            name="Echo",
        )
    )
)
assert runtime.validate() == []

result = asyncio.run(runtime.run("echo", input={"x": 1}))
print(result.status.value)
print(result.output)
```

## 常用公共导入

```python
from capability_runtime import (
    Runtime,
    RuntimeConfig,
    CustomTool,
    AgentSpec,
    AgentIOSchema,
    WorkflowSpec,
    Step,
    LoopStep,
    ParallelStep,
    ConditionalStep,
    InputMapping,
    CapabilitySpec,
    CapabilityKind,
    CapabilityResult,
    CapabilityStatus,
    NodeReport,
    HostRunSnapshot,
    ApprovalTicket,
    ResumeIntent,
    RuntimeServiceFacade,
    RuntimeServiceRequest,
    RuntimeServiceHandle,
    RuntimeSession,
    RuntimeFrameworkError,
    CapabilityNotFoundError,
)
```

## 快速排查

- `Capability not found`: 先补注册，再执行 `validate()`
- `needs_approval`: 读取 `NodeReport` 或 `HostRunSnapshot`
- `preflight` 报错：检查 `sdk_config_paths` / `skills_config`
- 想做宿主 streaming：看 `RuntimeServiceFacade`
