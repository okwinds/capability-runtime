---
name: rules-planner
description: "把规则文本整理为可审计的 plan.json"
---

# rules-planner

你负责把 `rules.txt` 中的规则，整理为 `plan.json`（结构化中间表示）。

要求：
- `plan.json` 必须可读、可审计、字段稳定；
- 不要在 plan 中写入环境相关信息；
- 输出必须能被后续“确定性执行器”消费（由 `rules-executor` 负责执行）。

## 产物契约（建议稳定字段）

- 文件名：`plan.json`（必须用 `file_write` 落盘）
- 建议 schema（示例）：
  - `version`: int（固定为 1）
  - `rules`: list
    - `id`: str（如 "r1"）
    - `if`: object（如 `{"field":"severity","eq":"high"}`）
    - `then`: object（如 `{"label":"urgent"}`）

## 必做清单（不得跳过）

1) 读取 `rules.txt`（可用 allowlisted `read_file`）。
2) 生成并 `file_write` 写出 `plan.json`（**禁止** 用 `shell_exec` 去“生成/写入 plan.json”）。
