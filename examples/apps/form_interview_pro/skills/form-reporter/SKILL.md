---
name: form-reporter
description: "产物与报告：落盘 submission.json 与 report.md，并把证据链指针写入报告"
---

# form-reporter

你负责把产物**稳定落盘**，并输出一份可复刻的 `report.md`。

## 产物契约（必须满足）

- `submission.json`
  - 内容：结构化字段（至少包含 `full_name/email/product/quantity`）
  - 必须是合法 JSON，UTF-8，建议 `indent=2`，文件末尾保留换行

- `report.md`
  - 必须包含：
    - 收集到的字段摘要（脱敏：email 可只展示 `@` 前后结构，避免完整暴露）
    - 产物清单（必须列出 `submission.json` 与 `report.md`）
    - 最小回归命令（例如 `python -c ...` 读取并断言 `submission.json`）
    - 证据链指针说明：`wal_locator/events_path` 由运行时在终态输出提供（此处可写占位与读取方法）

## 必做清单（不得跳过）

1) 使用 `file_write` 写入 `submission.json`。
2) （可选但推荐）使用 allowlisted 的 `list_dir` 或 `read_file` 做一次“文件存在性确认”。
3) 使用 `file_write` 写入 `report.md`。

## 注意事项
- 不要把产物写到 workspace 之外。
- 不要把真实密钥写入报告或 JSON。
