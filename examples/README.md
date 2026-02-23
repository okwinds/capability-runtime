# agently-skills-runtime Examples

渐进式示例库。每个目录独立可运行。

## 快速开始

```bash
pip install -e ".[dev]"
```

立即可运行（已存在）：

```bash
python examples/00_quickstart_capability_runtime/run.py
```

基础示例（BATCH1 已补齐 `run.py`，可直接运行）：

```bash
python examples/01_declare_and_run/run.py
```

## 示例索引

| # | 目录 | 演示内容 | 需要 LLM |
|---|------|---------|---------|
| 00 | 00_quickstart_capability_runtime | 30 秒离线体验 CapabilityRuntime（已可运行） | ❌ |
| 01 | 01_declare_and_run | 最小 AgentSpec 声明 + mock 执行 | ❌ |
| 02 | 02_workflow_sequential | 3 个 Agent 顺序执行 + InputMapping | ❌ |
| 03 | 03_workflow_loop | LoopStep：对列表中每个元素调用 Agent | ❌ |
| 04 | 04_workflow_parallel | ParallelStep：多个 Agent 并行执行 | ❌ |
| 05 | 05_workflow_conditional | ConditionalStep：条件分支 | ❌ |
| 08 | 08_nested_workflow | Workflow 嵌套 Workflow（BATCH 2） | ❌ |
| 09 | 09_full_scenario_mock | 完整场景模拟（BATCH 3） | ❌ |
| 10 | 10_bridge_wiring | 真实 LLM 接线（BATCH 3） | ✅ |
| 11 | 11_agent_domain_starter | Agent Domain 脚手架（BATCH 4；不含 SkillSpec） | ✅ |

> 注（方案2）：`06_skill_injection` / `07_skill_dispatch` 已不再提供可运行实现，仅保留迁移说明与指引。

## 参考应用（非示例）

如需更完整的参考应用/原型（可能依赖真实服务与配置），见：

- `archive/projects/`（已归档，不属于 runtime 主线交付物）
