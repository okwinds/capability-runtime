<div align="center">

[English](05-hosted-runtime-and-evidence.md) | [中文](05-hosted-runtime-and-evidence.zh-CN.md)

</div>

# Hosted Runtime And Evidence

Use these surfaces when the host application needs more than a terminal `output`.

## Evidence

- `NodeReport`: aggregated terminal evidence
- `events_path`: best-effort pointer to WAL events
- tool-call summaries: approval, status, and error-kind aggregation

For multimodal `precomposed_messages`, `NodeReport.meta` records only safe prompt
summaries:

- `prompt_modalities`
- `prompt_content_part_counts`
- `prompt_media_count`

It does not record full `messages[]`, URLs, base64 payloads, media bytes, prompt
text, `tool_calls`, or `tool_call_id`. Runtime UI events are still projection
events, not the audit source, and they do not project these multimodal prompt
summary fields.

Media or file outputs continue to be represented as artifact locators on:

- `CapabilityResult.artifacts`
- `NodeReport.artifacts`

Do not treat UI event evidence as the complete artifact truth source. The
terminal result and `NodeReport` are the stable evidence surfaces.

## Host Protocol

- `ApprovalTicket`
- `ResumeIntent`
- `HostRunSnapshot`

These are the stable host-facing objects for wait/resume and human approval flows.

## Service Facade

Use `RuntimeServiceFacade` when the host needs:

- a stable request/handle model
- JSONL or SSE framing
- session continuity via `RuntimeSession`
- a smaller RPC-friendly shape around the runtime
