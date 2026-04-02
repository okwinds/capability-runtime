<div align="center">

[English](README.md) | [中文](README.zh-CN.md)

</div>

# examples 历史归档（非主线）

本目录用于归档 `examples/` 下的历史示例（建设期早期迭代产物），它们多数基于旧入口/旧叙事，
在当前主线“统一 `Runtime` 唯一入口”的公共 API 下 **不保证可运行**。

归档目标：
- 减少误用：主线 `examples/` 仅保留当前推荐路径（可复制、可回归）。
- 保留追溯：历史示例仍可作为对照材料，便于查阅演进过程。

## 推荐从哪里开始（主线）

- 最短闭环（mock + bridge）：`examples/01_quickstart/`
- Workflow（顺序/循环/条件）：`examples/02_workflow/`
- 真实 LLM + tool_call + approvals + NodeReport：`examples/03_bridge_e2e/`
- TriggerFlow 顶层编排多个 `Runtime.run()`：`examples/04_triggerflow_orchestration/`

## 归档映射（原路径 → 现路径）

> 说明：此处仅记录目录迁移，不承诺这些示例在主线继续维护。

- `examples/00_prototype_validation/` → `archive/examples-legacy/00_prototype_validation/`
- `examples/00_quickstart_capability_runtime/` → `archive/examples-legacy/00_quickstart_capability_runtime/`
- `examples/01_declare_and_run/` → `archive/examples-legacy/01_declare_and_run/`
- `examples/02_workflow_sequential/` → `archive/examples-legacy/02_workflow_sequential/`
- `examples/03_workflow_loop/` → `archive/examples-legacy/03_workflow_loop/`
- `examples/04_workflow_parallel/` → `archive/examples-legacy/04_workflow_parallel/`
- `examples/05_workflow_conditional/` → `archive/examples-legacy/05_workflow_conditional/`
- `examples/06_skill_injection/` → `archive/examples-legacy/06_skill_injection/`
- `examples/07_skill_dispatch/` → `archive/examples-legacy/07_skill_dispatch/`
- `examples/08_nested_workflow/` → `archive/examples-legacy/08_nested_workflow/`
- `examples/09_full_scenario_mock/` → `archive/examples-legacy/09_full_scenario_mock/`
- `examples/10_bridge_wiring/` → `archive/examples-legacy/10_bridge_wiring/`
- `examples/11_agent_domain_starter/` → `archive/examples-legacy/11_agent_domain_starter/`
- `examples/12_host_lifecycle_toolkit_mvr/` → `archive/examples-legacy/12_host_lifecycle_toolkit_mvr/`

