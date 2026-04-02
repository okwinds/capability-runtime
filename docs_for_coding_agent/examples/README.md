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

## Regression Commands

```bash
pytest -q tests/test_coding_agent_examples_atomic.py
pytest -q tests/test_coding_agent_examples_recipes.py
```
