<div align="center">

[English](cheatsheet.md) | [中文](cheatsheet.zh-CN.md)

</div>

# Cheatsheet: Shortest Execution Loop

## Remember These Three Things

1. declare capabilities with `AgentSpec` / `WorkflowSpec`
2. execute through `Runtime.run()` / `Runtime.run_stream()`
3. read `NodeReport` / `HostRunSnapshot` for structured evidence

## Minimal Offline Example

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

## Common Public Imports

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

## Fast Troubleshooting

- `Capability not found`: register the capability and rerun `validate()`
- `needs_approval`: inspect `NodeReport` or `HostRunSnapshot`
- preflight failure: review `sdk_config_paths` or `skills_config`
- host-side streaming: start from `RuntimeServiceFacade`
