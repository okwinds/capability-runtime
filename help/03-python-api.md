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
- `RuntimeServiceFacade`
- `RuntimeServiceRequest`
- `RuntimeServiceHandle`
- `RuntimeSession`

## Errors

- `RuntimeFrameworkError`
- `CapabilityNotFoundError`
