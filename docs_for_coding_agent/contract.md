<div align="center">

[English](contract.md) | [中文](contract.zh-CN.md)

</div>

# Delivery Contract For Coding Tasks

When you implement changes in this repository, use this minimum loop:

1. confirm scope, acceptance criteria, and forbidden paths
2. update the test plan first
3. implement the smallest change inside the public `Runtime` contract
4. run offline regression
5. update public documentation that users or agents rely on

## Runtime Contract

- execution entrypoint: `Runtime.run()` / `Runtime.run_stream()`
- registration: `Runtime.register()` / `Runtime.register_many()`
- dependency check: `Runtime.validate()`
- requester selection: `RuntimeConfig.requester_strategy`, where
  `responses` is opt-in and `chat_completions` is the compatibility default
- model selection: `AgentSpec.llm_config["model"]` -> SDK `ChatRequest.model`;
  Agently settings configure transport only
- provider audit: preserve `NodeReport.usage.model`, `request_id`, `provider`,
  and token counts; provider-returned model wins over request model, request
  model wins over SDK placeholders
- Dynamic DAG preview: compile into `DynamicWorkflowPlan` and execute through
  registered capabilities only

## Workflow Checks

- every `Step.id` must be unique
- every `InputMapping.source` must resolve
- loop inputs must resolve to a list
- nesting depth is bounded by `RuntimeConfig.max_depth`

## Do Not

- add upstream execution dependencies to the protocol layer
- bypass `Runtime` by creating a second orchestration semantics path
- expose upstream-native requester, `TriggerFlowExecution`, `DynamicTask`,
  `Workspace`, `Action`, or `SkillsExecutor` objects as public contracts
- use Agently `SkillsExecutor` as a second skills execution path; SKILL.md
  authoring patterns may be reused, but skill injection/tool execution/approval/
  WAL/events/NodeReport evidence stay on `skills-runtime-sdk`
- document Agently settings as the runtime model precedence source
- drop provider `request_id` or `provider` while repairing model metadata
- hardcode business rules into runtime internals
- commit real `.env` files or private collaboration documents
