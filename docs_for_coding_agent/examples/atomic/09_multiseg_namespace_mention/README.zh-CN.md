# Atomic: 09_multiseg_namespace_mention（多段 namespace + strict mention）

本示例只教学一个能力点：**上游 v0.1.5+ 的 namespace 支持多段（1..7 segments）且顺序敏感**，并通过 strict mention 触发 skills 注入。

你将看到：
- overlay 使用 `skills.spaces[].namespace`（至少 3 段）
- strict mention 使用 `$[namespace].skill_name`
- WAL（events.jsonl）中出现 `skill_injected`，其 `mention_text` 可观察到完整 namespace

离线运行（用于回归）：

```bash
python docs_for_coding_agent/examples/atomic/09_multiseg_namespace_mention/run.py --workspace-root /tmp/caprt-atomic-09
```

