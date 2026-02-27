# Recipe: 05_invoke_capability_child_workflow（Agent → Workflow）

本配方示例演示 Agent 通过 `invoke_capability` 委托执行一个子 Workflow（仍保持协议层只承诺 Agent/Workflow）：

- outer agent 触发工具 `invoke_capability(capability_id="child.wf", input=...)`
- 子能力为 Workflow：内部顺序执行 2 个 mock Agent，并汇总输出
- 证据链：outer 的 NodeReport.tool_calls 可观察到 `invoke_capability`；WAL 包含 approvals/tool evidence
- 最小披露：tool 返回值以 artifact 指针与摘要为主

离线运行（用于回归）：

```bash
python docs_for_coding_agent/examples/recipes/05_invoke_capability_child_workflow/run.py --workspace-root /tmp/asr-recipe-05
```

