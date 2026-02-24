# examples/02_workflow

本目录演示一个完整的 Workflow：**顺序 + 循环 + 条件分支**（离线 mock 可跑）。

```bash
python examples/02_workflow/run.py
```

你将看到：
- `Step` 产出列表
- `LoopStep` 对列表逐项执行并收集结果（结果列表写入 `context.step_outputs[loop_id]`）
- `ConditionalStep` 根据上游字段选择分支

