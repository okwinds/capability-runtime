---
name: rules-executor
description: "确定性执行：plan.json + input.json -> result.json"
---

# rules-executor

你负责触发确定性执行（非 LLM 推理）：
- 输入：`plan.json` + `input.json`
- 输出：`result.json`

约束：
- 执行必须确定性（相同输入得到相同输出）；
- 允许使用 `shell_exec` 运行一个最小 Python 片段完成转换；
- 产物必须落盘到 workspace 根目录。

## 必做清单（不得跳过）

1) **必须使用 `shell_exec`** 执行确定性脚本生成 `result.json`（不要由 LLM“直接写 result.json 内容”冒充执行结果）。
2) 脚本必须只依赖 `plan.json` 与 `input.json`。
3) 脚本执行完成后，`result.json` 必须是合法 JSON。

## 推荐执行方式（示例）

- 如果 workspace 中已提供 `deterministic_exec_rules.py`（示例默认会写入），优先使用：
  - `argv`: `python deterministic_exec_rules.py`

- 使用内联 Python：
  - `argv`: `python -c "<代码>"`
  - 代码需要：
    - `json.load` 读取 `plan.json` 与 `input.json`
    - 根据 plan 中规则生成 `labels` 列表
    - `json.dump(..., open('result.json','w',...))` 写出
    - `print('RULES_OK')`
