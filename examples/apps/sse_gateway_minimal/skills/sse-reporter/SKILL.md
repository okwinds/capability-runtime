---
name: sse-reporter
description: "SSE 示例：生成 report.md 并在终态返回 wal_locator"
---

# sse-reporter

你负责在 SSE 场景中生成最小报告，并返回一个简短的终态输出。

## 产物契约（必须满足）

- `report.md`
  - 必须用 `file_write` 落盘到 workspace 根目录
  - 必须包含：topic、产物清单、证据链指针说明（`wal_locator/events_path` 由终态输出提供）

## 必做清单（不得跳过）

1) `update_plan` 标注进度（至少 2 步：开始 → 完成）。
2) `file_write(report.md)` 写入报告。
3) 最终输出一句简短确认（例如 `ok` 或 `done`）。
