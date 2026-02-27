# examples/05_workflow_skills_first

本目录演示一个“组合示例”：**Workflow 编排 skills-first Agent**（离线可回归）。

你将看到：
- Workflow 仍只引用 Agent/Workflow 原语（不引入 Skill 节点）
- 每个 Agent 以 skills 为主要驱动（system prompt 变薄）
- 每个 Agent 运行都会产生可审计证据链（WAL + NodeReport），Workflow 通过 `context.step_results[*].report` 持有每步的控制面证据

运行：

```bash
python examples/05_workflow_skills_first/run.py --workspace-root /tmp/asr-ex-05
```

