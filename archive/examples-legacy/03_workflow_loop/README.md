# 03_workflow_loop（循环编排：LoopStep + item.*）

**演示**：`LoopStep` 对列表中的每个元素调用同一个 Agent。

你会看到“先生成列表 → 再逐个处理 → 汇总结果”的标准模式如何声明化。

## 前置条件

```bash
pip install -e ".[dev]"
```

## 运行方法

```bash
python examples/03_workflow_loop/run.py
```

> 说明：`run.py` 已提供，可直接离线运行。

## 场景设计（通用、离线）

- Agent A `list_generator`：输入 `category` → 输出 `{"items": [{"name": "x"}, {"name": "y"}, {"name": "z"}]}`
- Agent B `item_processor`：输入 `item_name` → 输出 `{"processed": "x → PROCESSED"}`
- Workflow：A → LoopStep(B, `iterate_over="step.generate.items"`)

## 学到什么

- `LoopStep.iterate_over`：必须解析为 `list`，否则 LoopStep 直接失败
- `item` / `item.{key}`：循环内读取当前元素（由运行时注入到 context）
- `item_input_mappings`：把 `item.*` 映射到下游输入字段
- `collect_as`：循环结果收集字段名（默认 `results`）
- `fail_strategy`：循环失败策略（`abort/skip/collect`）

## 代码要点（run.py 需满足）

- 展示 `iterate_over` + `item_input_mappings` 的基本用法
- 展示 `item.name` 前缀的使用
- 展示默认 `collect_as="results"` 的行为（最终输出中是列表）
- 打印循环中的每个结果（便于确认“每个 item 都执行了”）
