<div align="center">

[English](03-python-api.md) | [中文](03-python-api.zh-CN.md)

</div>

# Python API

The supported public API is the package root import surface.

## Core

- `Runtime`
- `RuntimeConfig`
- `CustomTool`

Provider bridge additions:

- `ProviderRequesterStrategy`: `"chat_completions"` or `"responses"`.
- `ToolChoiceAfterToolResult`: explicit provider compatibility override after a
  tool result, currently `"none"` or `"auto"`.
- `RuntimeConfig.requester_strategy`: requester strategy, defaulting to
  `"chat_completions"` for legacy compatibility.
- `RuntimeConfig.max_dynamic_nodes`: Dynamic DAG preview hard limit.
- `RuntimeRecallBackend`: runtime-owned backend protocol for context recall
  adapters.
- `build_recall_context_pack` / `write_node_report_summary`: neutral
  recall context helpers exposed from the package root.

Requester selection does not select the business model. Use
`AgentSpec.llm_config["model"]` to set the runtime model; the lifecycle layer
copies it into SDK `ChatRequest.model` before the provider backend sends the wire
request. Agently settings remain transport settings.

## Capability Protocol

- `CapabilitySpec`
- `CapabilityKind`
- `CapabilityResult`
- `CapabilityStatus`
- `AgentSpec`
- `AgentIOSchema`
- `PromptRenderMode`
- `WorkflowSpec`
- `DynamicWorkflowNode`
- `DynamicWorkflowPlan`
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

### Multimodal Precomposed Messages

`precomposed_messages` can also carry OpenAI-compatible multimodal content
parts. This is an explicit host-controlled boundary: the runtime validates,
summarizes, and forwards the messages, but it does not download, transcode, OCR,
ASR, frame-sample, or otherwise manage media.

Supported `content` shapes:

- `str`: existing text-only message content.
- `list[dict]`: v1 stable content parts.

Supported v1 content parts:

```python
messages = [
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "Compare these images."},
            {
                "type": "image_url",
                "image_url": {
                    "url": "https://example.test/a.png",
                    "detail": "auto",
                },
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": "https://example.test/b.png",
                },
            },
        ],
    }
]
```

Rules and limits:

- `text.text` must be a string. Empty text is allowed.
- `image_url.url` must be a non-empty string. The runtime does not fetch or
  validate the URL.
- `image_url.detail`, when present, must be `auto`, `low`, or `high`.
- Multiple `image_url` parts are allowed. Image-only content part lists are also
  valid.
- Empty content part lists, unknown part types, unknown fields, non-finite
  numbers, and non-JSON-compatible message values fail fast with
  `INVALID_PROMPT_MESSAGES`.
- Reserved or provider-specific parts such as `input_audio`, `file`, and `video`
  are not accepted by v1. Add support through a future explicit contract instead
  of relying on passthrough.

For evidence, `NodeReport.meta` records only a minimal summary:

- `prompt_modalities`
- `prompt_content_part_counts`
- `prompt_media_count`

It does not record full `messages[]`, full URLs, base64 payloads, media content,
prompt text, `tool_calls`, `tool_call_id`, or other provider extra fields.
Runtime UI events also do not project these prompt summary fields.

Multimodal outputs continue to use existing artifact locators:

- `CapabilityResult.artifacts: list[str]`
- `NodeReport.artifacts: list[str]`

The runtime does not add a parallel binary output field for images, audio, video,
or files.

`NodeReport.meta` records prompt evidence such as `prompt_render_mode`, `prompt_profile`, `prompt_hash`, message count, roles, and composer version. It does not record the full prompt text or full `messages[]` payload.

## Evidence And Host Surfaces

- `NodeReport`
- `ApprovalTicket`
- `ResumeIntent`
- `HostRunSnapshot`
- `WorkflowRunSnapshot` lifecycle fields are additive. Consumers may read
  `lifecycle_state`, `execution_id`, `state_version`, `intervention_mode`,
  `pending_interventions`, and `close_reason` when present, while older event
  consumers can ignore them.
- `RuntimeServiceFacade`
- `RuntimeServiceRequest`
- `RuntimeServiceHandle`
- `RuntimeSession`

## Runtime Capability Previews

Responses bridge:

```python
from capability_runtime import RuntimeConfig

cfg = RuntimeConfig(mode="bridge", requester_strategy="responses")
```

`"responses"` is opt-in. The default remains `"chat_completions"`, and
`sdk_backend` injection still takes precedence for offline tests.

Real provider audit:

- Build the bridge transport with `build_openai_provider_requester_factory(...)`
  and select the lane through `RuntimeConfig.requester_strategy`.
- `NodeReport.usage.model` prefers provider usage `model`, then falls back to
  `ChatRequest.model`.
- `NodeReport.usage.request_id` and `NodeReport.usage.provider` must be
  preserved when returned by the provider/gateway.
- Agently settings configure transport; do not rely on them as the only model
  configuration path.

Dynamic DAG preview:

```python
plan = runtime.compile_dynamic_workflow_plan(task_dag_like_mapping)
result = await runtime.run_dynamic_workflow(plan, input={"topic": "release"})
```

Compile TaskDAG-like data into the runtime-owned `DynamicWorkflowPlan`; do not
pass upstream-native `TaskDAG` / `DynamicTask` objects through application code as
stable contracts. Nodes execute only through registered capability ids, with
fail-closed `DYNAMIC_DAG_*` diagnostics and bounded `max_dynamic_nodes`.

Recall context preview accepts a runtime-owned `RuntimeRecallBackend` and exposes
a neutral `RuntimeRecallContextPack`; it is not a WAL or NodeReport replacement.
An upstream Workspace can be adapted behind that backend protocol, but downstream
code should not depend on the upstream-native object. Action artifact evidence is
exposed as redacted artifact references and `NodeReport.meta` summaries, never
raw artifact content.

Agently `SkillsExecutor` is not a `capability-runtime` skills driver. You may
reuse its general `SKILL.md` authoring discipline, but `AgentSpec.skills` still
flows through `skills-runtime-sdk` for skill injection, tools, approvals, WAL,
events, and `NodeReport` evidence.

## Errors

- `RuntimeFrameworkError`
- `CapabilityNotFoundError`
