<div align="center">

[English](README.md) | [中文](README.zh-CN.md)

</div>

# 05_dynamic_dag_preview

Preview example for runtime-owned Dynamic DAG alignment.

The downstream contract is `capability_runtime`:

- compile TaskDAG-like data into a runtime-owned `DynamicWorkflowPlan`
- keep node count bounded by `max_dynamic_nodes`
- execute nodes only through registered capabilities
- record graph and node evidence in NodeReport/UI events

This example does not import upstream-native `TaskDAG` or `DynamicTask` objects.

```bash
python examples/05_dynamic_dag_preview/run.py
```
