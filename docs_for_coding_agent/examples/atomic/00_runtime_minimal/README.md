# Atomic: 00_runtime_minimal（Runtime.register/validate/run + WAL/NodeReport）

本示例只教学一个能力点：**最小 Runtime 闭环**。

你将看到：
- 如何注册 `AgentSpec`
- 如何用 `Runtime.run()` 执行一次离线 run
- 如何通过 `NodeReportV2.events_path` 找到 WAL（events.jsonl）

离线运行（用于回归）：

```bash
python docs_for_coding_agent/examples/atomic/00_runtime_minimal/run.py --workspace-root /tmp/asr-atomic-00
```

