# 12_host_lifecycle_toolkit_mvr

最小可复刻示例：Host 生命周期工具箱（MVR）——TurnDelta / HistoryAssembler / SystemPromptProvider / approvals（阻塞等待）/ resume helper。

说明：

- 本示例不依赖真实 LLM：使用 `agent_sdk` 的 Fake backend 触发一次 `file_write` 工具调用与 approvals 证据链。
- `system/developer` 提示词在 MVR 中不通过 `initial_history` 注入，而通过 SDK prompt/config overlays 注入（示例中仅演示配置形态与证据链摘要，不落明文）。
- history 真相源由 Host 管理：示例以 in-memory `TurnDelta[]` 作为存储。

## 运行

```bash
python examples/12_host_lifecycle_toolkit_mvr/run.py
```

运行后会在临时工作目录下生成：

- `.skills_runtime_sdk/runs/<run_id>/events.jsonl`（WAL）
- `hello.txt`（由 `file_write` 写入）

你可以用输出的 `events_path` 再运行 resume helper（示例代码中已演示）。

