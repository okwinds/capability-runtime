<div align="center">

[English](00-mental-model.md) | [中文](00-mental-model.zh-CN.md)

</div>

# Mental Model: Protocol -> Runtime -> Report

This repository is not a prompt-playground project and not a second agent
framework. Treat it as a contract-convergence layer around a smaller public
runtime surface.

## 1. Protocol

- declare capabilities with `AgentSpec` and `WorkflowSpec`
- define inputs, outputs, and composition edges
- do not execute anything here

## 2. Runtime

- run everything through `Runtime.run()` or `Runtime.run_stream()`
- switch transport/execution flavor with `RuntimeConfig.mode`
- keep the host-facing surface stable and testable

## 3. Report

- read `NodeReport` first when you need structured evidence
- use `output` as the data plane, not as the main orchestration contract
- expect approval/tool/WAL summaries to be aggregated into the terminal report

## Upstream Responsibilities

- `skills-runtime-sdk`: skills, tools, approvals, WAL, and event truth
- `Agently`: OpenAI-compatible transport and workflow internals
- `capability-runtime`: the smaller runtime contract that hosts can integrate

## Provider Bridge Boundary

- Responses bridge is opt-in through `RuntimeConfig.requester_strategy="responses"`;
  the default remains `chat_completions`.
- Real provider wiring is ordered: verify `models`, configure
  `OpenAICompatible` for provider chat, configure `OpenAIResponsesCompatible`
  only for `/responses`, then smoke runtime chat and runtime responses paths.
- Runtime model selection flows through `AgentSpec.llm_config["model"]` into SDK
  `ChatRequest.model`. Agently settings are transport settings and must not be
  treated as the model precedence source.
- Dynamic DAG preview uses runtime-owned `DynamicWorkflowPlan`, not raw Agently
  `TaskDAG` / `DynamicTask` objects as downstream contracts.
- Workflow lifecycle, Workspace/Recall context, and Action artifact evidence are
  summarized into `WorkflowRunSnapshot`, `NodeReport`, and UI events. They do not
  replace WAL or expose upstream-native objects.
- Provider audit lives in `NodeReport.usage`: keep `model`, `request_id`,
  `provider`, and token counts when available; provider model wins over request
  model, and request model wins over SDK placeholders.

## Suggested Code Reading Order

1. `src/capability_runtime/__init__.py`
2. `src/capability_runtime/runtime.py`
3. `src/capability_runtime/protocol/`
4. `src/capability_runtime/service_facade.py`
5. `src/capability_runtime/reporting/node_report.py`
