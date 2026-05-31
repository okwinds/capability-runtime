<div align="center">

[English](README.md) | [中文](README.zh-CN.md)

</div>

# docs_for_coding_agent

This pack gives a coding agent the minimum public context needed to work in this
repository without scanning the whole tree first.

It focuses on:

- the public runtime surface
- the shortest runnable examples
- the regression guardrails that define "done"
- runtime capability previews without leaking upstream native objects into the
  public contract

## Recommended Reading Order

1. [cheatsheet.md](cheatsheet.md) - shortest execution loop
2. [00-mental-model.md](00-mental-model.md) - protocol, runtime, and evidence boundaries
3. [contract.md](contract.md) - delivery contract and change workflow
4. [capability-coverage-map.md](capability-coverage-map.md) - capability to evidence mapping
5. [examples/README.md](examples/README.md) - offline-regression examples

For provider bridge upgrade work, read the upgrade spec first:
`docs/specs/upgrade-agently-4.1.3.1.md`. The coding rule is simple: downstream
code depends on `capability_runtime`, not upstream-native requester, TaskDAG,
Workspace, Action, or TriggerFlow execution objects.

Real-provider work must also preserve the runtime wiring order:
`models` check -> `OpenAICompatible` provider chat transport ->
`OpenAIResponsesCompatible` provider responses transport when available -> runtime
`chat_completions` smoke -> runtime `responses` smoke. The runtime model entry
is `AgentSpec.llm_config["model"]` / SDK `ChatRequest.model`; Agently settings
only configure transport. Audit `NodeReport.usage.model`,
`NodeReport.usage.request_id`, and `NodeReport.usage.provider` before declaring
a provider bridge change done.

## Scope

This pack is intentionally compact. It is not a second documentation system.

- use `help/` for user-facing guidance
- use `examples/` for human-facing runnable examples
- use this directory when an agent needs a small, operationally useful context pack

## Example Packs

- `examples/atomic/`: one capability point per example
- `examples/recipes/`: multi-step delivery patterns

Regression entrypoints:

```bash
python -m pytest tests/test_coding_agent_examples_atomic.py -q
python -m pytest tests/test_coding_agent_examples_recipes.py -q
```
