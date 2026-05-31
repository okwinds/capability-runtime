# 05_dynamic_dag_preview

Runtime-owned Dynamic DAG 对齐预览示例。

下游稳定契约是 `capability_runtime`：

- 将 TaskDAG-like 数据编译为本仓 `DynamicWorkflowPlan`
- 用 `max_dynamic_nodes` 限制图规模
- 节点只通过已注册 capability 执行
- 图与节点证据进入 NodeReport / UI events

本示例不 import 上游原生 `TaskDAG` 或 `DynamicTask` 对象。

```bash
python examples/05_dynamic_dag_preview/run.py
```
