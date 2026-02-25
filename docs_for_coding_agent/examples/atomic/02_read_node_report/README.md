# Atomic: 02_read_node_report（如何读 NodeReportV2）

本示例只教学一个能力点：**如何从 NodeReportV2 中提取稳定证据**。

你将看到：
- `node_report.tool_calls` 中的 `name/ok/error_kind/requires_approval/approval_decision`
- `node_report.activated_skills`（skills-first 证据）

离线运行（用于回归）：

```bash
python docs_for_coding_agent/examples/atomic/02_read_node_report/run.py --workspace-root /tmp/asr-atomic-02
```

