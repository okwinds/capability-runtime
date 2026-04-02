<div align="center">

[English](README.md) | [中文](README.zh-CN.md)

</div>

# Examples

This directory contains the public runnable examples for `capability-runtime`.

## Progressive Runtime Examples

These are the mainline examples to learn the runtime surface from smallest to larger:

| Directory | Focus | Real model required |
|---|---|---|
| `01_quickstart/` | smallest loop with `Runtime` | optional |
| `02_workflow/` | sequential, loop, and conditional workflow execution | no |
| `03_bridge_e2e/` | real backend bridge path and evidence flow | yes |
| `04_triggerflow_orchestration/` | host-side orchestration around multiple runtime calls | yes |
| `05_workflow_skills_first/` | workflow composition with skills-first agents | no |

## App-Style Examples

`examples/apps/` contains slightly more end-to-end entrypoints:

- `form_interview_pro`
- `incident_triage_assistant`
- `ci_failure_triage_and_fix`
- `rules_parser_pro`
- `sse_gateway_minimal`
- `ui_events_showcase`

These examples are useful when you want to see:

- terminal-style flows
- HTTP/SSE framing
- UI event projection
- offline vs real execution boundaries

## Quick Commands

```bash
python examples/01_quickstart/run_mock.py
python examples/02_workflow/run.py
python examples/apps/sse_gateway_minimal/run.py
```

For coding-agent-specific examples, switch to
[docs_for_coding_agent/examples/README.md](../docs_for_coding_agent/examples/README.md).
