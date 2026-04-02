# Atomic: 01_sdk_native_minimal（Runtime.run_stream：事件流 → 终态）

本示例只教学一个能力点：**Runtime.run_stream() 的流式协议**。

你将看到：
- `run_stream()` 会先产出 `AgentEvent`（过程事件），最后产出 `CapabilityResult`（终态）
- 离线注入 FakeChatBackend 仍能产出 WAL/NodeReport

离线运行（用于回归）：

```bash
python docs_for_coding_agent/examples/atomic/01_sdk_native_minimal/run.py --workspace-root /tmp/caprt-atomic-01
```

