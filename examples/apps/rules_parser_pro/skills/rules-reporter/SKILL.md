---
name: rules-reporter
description: "输出 report.md，记录产物与证据链检查点"
---

# rules-reporter

你负责输出 `report.md`，至少包含：
- 输入文件：`rules.txt`、`input.json`
- 产物文件：`plan.json`、`result.json`、`report.md`
- 验证命令（最小可复现）
- wal_locator（或 events_path）等可追溯信息

## 必做清单（不得跳过）

1) 必须用 `file_write` 写出 `report.md`。
2) 验证命令必须是离线确定性的（例如读取 JSON 并断言字段存在）。
3) 证据链指针说明：`wal_locator/events_path` 由运行时终态输出提供（写明在哪里看）。
