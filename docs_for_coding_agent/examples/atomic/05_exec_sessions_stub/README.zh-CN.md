# Atomic: 05_exec_sessions_stub（exec_command/write_stdin：离线 stub）

本示例只教学一个能力点：**exec sessions 注入点**。

你将看到：
- 如何向 `RuntimeConfig.exec_sessions` 注入一个 stub provider
- 如何在离线环境运行 `exec_command`（不依赖真实 PTY）
- 如何在 NodeReport.tool_calls 中看到 `session_id/stdout/exit_code`

离线运行（用于回归）：

```bash
python docs_for_coding_agent/examples/atomic/05_exec_sessions_stub/run.py --workspace-root /tmp/caprt-atomic-05
```

