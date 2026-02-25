---
name: ci-qa-reporter
description: "验证与报告：运行最小回归并输出 report.md"
---

# ci-qa-reporter

你负责“回归验证 → 输出报告”。

## 必做清单（不得跳过）

1) **必须再次运行测试**（用 `shell_exec`）确认修复有效：
   - 推荐：`python -m pytest -q test_app.py`

2) **必须落盘 `report.md`**（用 `file_write`）：
   - 问题摘要（1~2 行）
   - 修复点（说明改了哪一行/哪个函数）
   - 验证命令（必须写出可复制的命令）
   - 证据链指针说明：`wal_locator/events_path` 由运行时终态输出提供（写明在哪里看）

## 禁止事项
- 禁止仅在自然语言里说“已通过”，但没有实际执行回归命令。
