# 04_workflow_parallel（并行编排：ParallelStep）

**演示**：`ParallelStep` 让多个 Agent 并行执行，并把并行结果交给后续步骤汇总。

适用于“同一份输入，多个角度/策略并行处理”的模式。

## 前置条件

```bash
pip install -e ".[dev]"
```

## 运行方法

```bash
python examples/04_workflow_parallel/run.py
```

> 说明：`run.py` 已提供，可直接离线运行。

## 场景设计（通用、离线）

- Agent A `analyzer_alpha`：输入 `data` → 输出 `{"analysis": "alpha perspective"}`
- Agent B `analyzer_beta`：输入 `data` → 输出 `{"analysis": "beta perspective"}`
- Agent C `analyzer_gamma`：输入 `data` → 输出 `{"analysis": "gamma perspective"}`
- Agent D `synthesizer`：输入 3 个分析结果 → 输出综合报告
- Workflow：ParallelStep([A, B, C]) → D

## 学到什么

- `ParallelStep.branches`：并行分支是一组“可执行 step”
- `ParallelStep.join_strategy`：
  - `all_success`：任一分支失败 → 整步失败
  - `any_success`：至少一个成功，否则失败
  - `best_effort`：尽量执行（失败不必然导致整步失败，视实现约定）
- 如何用 `step.{branch_id}` 引用并行分支的输出供后续步骤消费

## 代码要点（run.py 需满足）

- 展示 `branches` 与 `join_strategy`
- 展示并行步骤的输出如何被后续步骤通过 `step.{branch_id}` 引用
- 输出结构尽量可读（便于目视验证）
