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
| `04_triggerflow_orchestration/` | runtime workflow lifecycle snapshot through `Runtime` / `WorkflowSpec` | no |
| `05_workflow_skills_first/` | workflow composition with skills-first agents | no |
| `05_dynamic_dag_preview/` | Dynamic DAG preview via runtime-owned plan | no |
| `06_responses_bridge/` | Responses requester opt-in configuration preview | optional |
| `08_workspace_recall_preview/` | neutral Workspace/Recall context pack preview | no |
| `09_action_artifact_evidence/` | Action artifact reference evidence summary | no |
| `10_runtime_bridge_showcase/` | live runtime bridge showcase with server-side provider config | yes |

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
python examples/05_dynamic_dag_preview/run.py
python examples/06_responses_bridge/run.py
python examples/08_workspace_recall_preview/run.py
python examples/09_action_artifact_evidence/run.py
python examples/10_runtime_bridge_showcase/server.py --host 127.0.0.1 --port 8090
python examples/apps/sse_gateway_minimal/run.py
```

Capability preview rule: use `capability_runtime` contracts. Responses is
opt-in and Dynamic DAGs compile into `DynamicWorkflowPlan`; downstream examples
must not depend on upstream-native requester, `TaskDAG`, `DynamicTask`,
Workspace, Action, or TriggerFlow execution objects.

Real provider examples use a fixed wiring order: verify the model with the
gateway, configure provider chat transport, configure provider responses transport
only when `/responses` exists, then run runtime chat and runtime responses
smokes. The runtime request model must come from `AgentSpec.llm_config.model`
so the SDK `ChatRequest.model` and `NodeReport.usage.model` can be audited.
`NodeReport.usage.request_id` and `NodeReport.usage.provider` should survive
both chat and responses paths.

For coding-agent-specific examples, switch to
[docs_for_coding_agent/examples/README.md](../docs_for_coding_agent/examples/README.md).
