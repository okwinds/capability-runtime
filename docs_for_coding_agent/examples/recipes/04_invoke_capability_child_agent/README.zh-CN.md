# Recipe: 04_invoke_capability_child_agent（渐进式披露：委托子 Agent）

本配方示例演示“渐进式披露”的最小可回归闭环：

- outer agent（skills-first）在运行中触发工具 `invoke_capability`
- 由宿主工具 handler 委托执行一个子 Agent（`capability_id="child.echo"`）
- 证据链：`NodeReport.tool_calls` 可观察到 `invoke_capability`，且 WAL 中包含 approvals/tool evidence
- tool 返回值遵守最小披露：只返回摘要与 artifact 指针

离线运行（用于回归）：

```bash
python docs_for_coding_agent/examples/recipes/04_invoke_capability_child_agent/run.py --workspace-root /tmp/caprt-recipe-04
```

