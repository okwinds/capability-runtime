<div align="center">

[English](README.md) | [中文](README.zh-CN.md)

</div>

# 02_workflow_sequential（顺序编排：Step + InputMapping）

**演示**：3 个 Agent 顺序执行，展示 `Step` + `InputMapping` 的数据流转方式。

核心目标是把一个“多步处理”表达成可读、可回归的 Workflow 声明。

## 前置条件

```bash
pip install -e ".[dev]"
```

## 运行方法

```bash
python examples/02_workflow_sequential/run.py
```

> 说明：`run.py` 已提供，可直接离线运行。

## 场景设计（通用、离线）

- Agent A `idea_generator`：输入 `topic` → 输出 `{"ideas": ["idea1", "idea2", "idea3"]}`
- Agent B `idea_evaluator`：输入 `ideas` → 输出 `{"best_idea": "idea2", "score": 85}`
- Agent C `report_writer`：输入 `best_idea + score` → 输出 `{"report": "..."}`
- Workflow：A → B → C，通过 `InputMapping` 传递数据

## 学到什么

- `WorkflowSpec`：Workflow 元能力声明（`steps` 按声明顺序执行）
- `Step`：最基础的编排单元（执行一个 capability）
- `InputMapping`：把 `context/previous/step.*` 映射为下游输入字段
- `ExecutionContext.step_outputs`：步骤输出缓存（`step_id → output`）

## 代码要点（run.py 需满足）

- 展示 `InputMapping` 的三种常用 source：
  - `context.`：从 context bag 读取
  - `previous.`：从上一步输出读取
  - `step.X.Y`：从指定步骤输出字段读取
- mock adapter 根据 `agent_id` 返回不同结果
- 运行时打印每一步的输出（便于目视验证数据流）
