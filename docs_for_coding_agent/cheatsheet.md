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

Capability preview imports, once exported by the runtime package:

```python
from capability_runtime import (
    ProviderRequesterStrategy,
    DynamicWorkflowNode,
    DynamicWorkflowPlan,
    RuntimeRecallBackend,
    RuntimeRecallContextPack,
)
```

Use `RuntimeConfig.requester_strategy="responses"` only for explicit Responses
opt-in. Do not import upstream-native requester, workflow, Workspace, DynamicTask,
Action, or SkillsExecutor objects in downstream code. Agently SkillsExecutor
patterns are authoring guidance only; runtime skills execution remains
`skills-runtime-sdk`.

## Provider Bridge Runbook

```python
spec = AgentSpec(
    base=CapabilitySpec(id="agent.real", kind=CapabilityKind.AGENT, name="Real"),
    llm_config={"model": os.environ["MODEL_NAME"]},
)
cfg = RuntimeConfig(mode="bridge", requester_strategy="chat_completions")
```

Order for real provider checks:

1. Confirm `MODEL_NAME` via the gateway or `/models`.
2. Build `provider_requester_factory` with `build_openai_provider_requester_factory(...)`.
3. Run runtime chat with `requester_strategy="chat_completions"`.
4. Run runtime responses with `requester_strategy="responses"` only when `/responses` exists.

Model priority:

- application entry: `AgentSpec.llm_config["model"]`
- runtime request: SDK `ChatRequest.model`
- provider audit: provider usage `model` when returned, otherwise request model
- transport only: Agently settings `base_url`, `auth`, headers, requester config

Before closing a real provider task, inspect `NodeReport.usage.model`,
`request_id`, `provider`, and token counts. Do not accept an SDK placeholder
model as real provider evidence when request/provider model evidence exists.

## Fast Troubleshooting

- `Capability not found`: register the capability and rerun `validate()`
- `needs_approval`: inspect `NodeReport` or `HostRunSnapshot`
- preflight failure: review `sdk_config_paths` or `skills_config`
- host-side streaming: start from `RuntimeServiceFacade`
- provider model mismatch: check `AgentSpec.llm_config.model` before Agently
  settings, then inspect `NodeReport.usage`
- Dynamic DAG failure: check `DYNAMIC_DAG_*` diagnostics, node count, and whether
  every node binding resolves to a registered capability.
