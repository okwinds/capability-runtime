# Atomic: 03_preflight_gate（preflight: off/warn/error）

本示例只教学一个能力点：**skills preflight gate**。

你将看到：
- overlay 中出现不被上游支持的 legacy 字段（如 `skills.roots`）时
- `preflight_mode="error"` 会 fail-closed（不启动执行引擎；`events_path=None`）
- `preflight_mode="warn"` 会继续执行，但把问题记录进 `NodeReportV2.meta.preflight_issues`

离线运行（用于回归）：

```bash
python docs_for_coding_agent/examples/atomic/03_preflight_gate/run.py --workspace-root /tmp/asr-atomic-03
```

