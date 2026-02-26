# Atomic: 04_custom_tool（宿主注入自定义工具）

本示例只教学一个能力点：**custom_tools 注入**。

你将看到：
- 如何用 `RuntimeConfig.custom_tools` 注入一个宿主工具 `host_ping`
- 如何在 NodeReport.tool_calls 中看到该工具的证据

离线运行（用于回归）：

```bash
python docs_for_coding_agent/examples/atomic/04_custom_tool/run.py --workspace-root /tmp/asr-atomic-04
```

