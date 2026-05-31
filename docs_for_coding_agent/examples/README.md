<div align="center">

[English](README.md) | [中文](README.zh-CN.md)

</div>

# docs_for_coding_agent/examples

Offline-regression example library for coding agents.

## Structure

- `atomic/`: one capability point per example
- `recipes/`: compositional patterns for realistic delivery flows

## Suggested Path

1. Start from `atomic/00_runtime_minimal`
2. Move through `atomic/*` for tooling and evidence primitives
3. Use `recipes/*` for multi-step delivery patterns

For runtime capability previews, use the human-facing examples:

- `examples/05_dynamic_dag_preview/`
- `examples/06_responses_bridge/`
- `examples/08_workspace_recall_preview/`
- `examples/09_action_artifact_evidence/`

They are still capability-runtime examples. They should not teach downstream
agents to import upstream-native objects directly.

For real provider examples, set the model through `AgentSpec.llm_config.model`
and check `NodeReport.usage` for `model`, `request_id`, and `provider`.
Agently settings are only the transport lane.

## Regression Commands

```bash
pytest -q tests/test_coding_agent_examples_atomic.py
pytest -q tests/test_coding_agent_examples_recipes.py
```
