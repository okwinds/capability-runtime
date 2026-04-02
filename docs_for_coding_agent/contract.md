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

## Workflow Checks

- every `Step.id` must be unique
- every `InputMapping.source` must resolve
- loop inputs must resolve to a list
- nesting depth is bounded by `RuntimeConfig.max_depth`

## Do Not

- add upstream execution dependencies to the protocol layer
- bypass `Runtime` by creating a second orchestration semantics path
- hardcode business rules into runtime internals
- commit real `.env` files or private collaboration documents
