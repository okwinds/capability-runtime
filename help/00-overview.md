<div align="center">

[English](00-overview.md) | [中文](00-overview.zh-CN.md)

</div>

# Overview

`capability-runtime` narrows a larger upstream toolchain into a smaller host API:

- declare capabilities with `AgentSpec` and `WorkflowSpec`
- register and validate them in `Runtime`
- run them and read terminal evidence from `CapabilityResult.node_report`

Use this repository when you want:

- a smaller host-facing runtime contract
- testable capability orchestration
- evidence-first integration with tools, approvals, and WAL
