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

## Recommended Reading Order

1. [cheatsheet.md](cheatsheet.md) - shortest execution loop
2. [00-mental-model.md](00-mental-model.md) - protocol, runtime, and evidence boundaries
3. [contract.md](contract.md) - delivery contract and change workflow
4. [capability-coverage-map.md](capability-coverage-map.md) - capability to evidence mapping
5. [examples/README.md](examples/README.md) - offline-regression examples

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
