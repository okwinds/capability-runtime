# 05_workflow_conditional（条件分支：ConditionalStep）

**演示**：`ConditionalStep` 根据上一步输出选择不同分支执行。

适用于“先分类/判定 → 再走不同处理路径”的模式。

## 前置条件

```bash
pip install -e ".[dev]"
```

## 运行方法

```bash
python examples/05_workflow_conditional/run.py
```

> 说明：`run.py` 已提供，可直接离线运行。

## 场景设计（通用、离线）

- Agent A `classifier`：输入 `text` → 输出 `{"category": "positive"|"negative"|"neutral"}`
- Agent B `positive_handler`：输入 `text` → 输出 `{"action": "celebrate!"}`
- Agent C `negative_handler`：输入 `text` → 输出 `{"action": "investigate..."}`
- Agent D `neutral_handler`（default）：输入 `text` → 输出 `{"action": "monitor"}`
- Workflow：A → ConditionalStep(`condition_source="step.classify.category"`, `branches=...`, `default=...`)

## 学到什么

- `ConditionalStep.condition_source`：从 context 中解析条件值（会转成字符串做分支匹配）
- `ConditionalStep.branches`：条件值 → step 的映射
- `ConditionalStep.default`：无匹配时的默认分支（不提供则失败）
- 如何通过打印“走了哪条路径”快速验证分支逻辑

## 代码要点（run.py 需满足）

- 展示 `condition_source + branches + default` 的基本用法
- 运行两次，分别触发不同分支，打印走了哪条路径
