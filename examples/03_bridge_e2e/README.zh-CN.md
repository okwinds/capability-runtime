# examples/03_bridge_e2e

本目录用于在**有真实 LLM provider** 的环境下，跑通一次 bridge 执行并观察证据链：

- `Runtime.run_stream()` 转发上游事件
- 触发一次需要审批的 tool call（示例为 `file_write`）
- 最终 `CapabilityResult.node_report` 中可看到 tool_calls / approvals / events_path 等证据

## 运行

```bash
python -m pip install -e ".[dev]"
cp examples/03_bridge_e2e/.env.example examples/03_bridge_e2e/.env
python examples/03_bridge_e2e/run.py
```

说明：
- 缺少 `.env` 或必要环境变量时，示例会打印提示并返回非 0；只有显式设置
  `CAPRT_EXAMPLE_ALLOW_SKIP=1` 时才作为离线回归跳过并返回 0。
