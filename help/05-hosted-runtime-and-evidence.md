<div align="center">

[English](05-hosted-runtime-and-evidence.md) | [中文](05-hosted-runtime-and-evidence.zh-CN.md)

</div>

# Hosted Runtime And Evidence

Use these surfaces when the host application needs more than a terminal `output`.

## Evidence

- `NodeReport`: aggregated terminal evidence
- `events_path`: best-effort pointer to WAL events
- tool-call summaries: approval, status, and error-kind aggregation

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
