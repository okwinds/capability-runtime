---
name: incident-reporter
description: "报告：输出 report.md 并记录 wal_locator 等证据链指针"
---

# incident-reporter

你负责输出 `report.md`，用于把本次排障闭环“可复刻、可追溯”地记录下来。

## 产物契约（必须满足）

- `report.md` 必须包含：
  - 输入：`incident.log`
  - 关键结论摘要（1~3 条）
  - 产物清单：`runbook.md`、`report.md`
  - 最小复现/验证命令（离线、确定性）：例如 `python -c "print(open('runbook.md').read()[:20])"` 之类
  - 证据链指针说明：`wal_locator/events_path` 由运行时终态输出提供（写明在哪里看）

## 必做清单（不得跳过）

1) 用 `file_write` 写入 `report.md`。
2) 报告中不要粘贴 incident.log 全量内容（避免泄露/噪音）；只保留必要片段与摘要。
