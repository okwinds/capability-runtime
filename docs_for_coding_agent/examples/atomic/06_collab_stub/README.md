# Atomic: 06_collab_stub（spawn_agent/wait：离线 stub）

本示例只教学一个能力点：**collab 注入点**。

你将看到：
- 如何向 `RuntimeConfig.collab_manager` 注入一个 stub manager
- 如何离线跑通 `spawn_agent/send_input/wait/close_agent`
- 如何在 NodeReportV2.tool_calls 中观察 `data.results[*].final_output`

离线运行（用于回归）：

```bash
python docs_for_coding_agent/examples/atomic/06_collab_stub/run.py --workspace-root /tmp/asr-atomic-06
```

