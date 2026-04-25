<div align="center">

[English](03-python-api.md) | [中文](03-python-api.zh-CN.md)

</div>

# Python API

The supported public API is the package root import surface.

## Core

- `Runtime`
- `RuntimeConfig`
- `CustomTool`

## Capability Protocol

- `CapabilitySpec`
- `CapabilityKind`
- `CapabilityResult`
- `CapabilityStatus`
- `AgentSpec`
- `AgentIOSchema`
- `PromptRenderMode`
- `WorkflowSpec`
- `Step`
- `LoopStep`
- `ParallelStep`
- `ConditionalStep`
- `InputMapping`

## Agent Prompt Rendering

`AgentSpec` supports prompt rendering strategies for production generation tasks:

- `structured_task`: the default compatible mode. Runtime builds the SDK task text from `system_prompt`, description, input, output schema, and skill mentions.
- `direct_task_text`: the host provides final task text in `input["_runtime_prompt"]["task_text"]`.
- `precomposed_messages`: the host provides final provider messages in `input["_runtime_prompt"]["messages"]`.

`_runtime_prompt` is a reserved runtime control envelope. It is not rendered as business input and should not be reused as an application field name.

Example:

```python
from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec

spec = AgentSpec(
    base=CapabilitySpec(id="writer", kind=CapabilityKind.AGENT, name="Writer"),
    prompt_render_mode="precomposed_messages",
    prompt_profile="generation_direct",
)

result = await runtime.run(
    "writer",
    input={
        "_runtime_prompt": {
            "messages": [
                {"role": "system", "content": "..."},
                {"role": "user", "content": "..."},
            ],
            "trace": {"prompt_hash": "sha256:<64 lowercase hex>"},
        }
    },
)
```

`NodeReport.meta` records prompt evidence such as `prompt_render_mode`, `prompt_profile`, `prompt_hash`, message count, roles, and composer version. It does not record the full prompt text or full `messages[]` payload.

## Evidence And Host Surfaces

- `NodeReport`
- `ApprovalTicket`
- `ResumeIntent`
- `HostRunSnapshot`
- `RuntimeServiceFacade`
- `RuntimeServiceRequest`
- `RuntimeServiceHandle`
- `RuntimeSession`

## Errors

- `RuntimeFrameworkError`
- `CapabilityNotFoundError`
