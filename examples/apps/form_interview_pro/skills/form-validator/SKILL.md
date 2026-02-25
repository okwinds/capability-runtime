---
name: form-validator
description: "表单校验：用最小确定性校验保证字段合法"
---

# form-validator

你负责对表单字段做**最小确定性校验**，并在失败时给出明确的修复建议。

## 必做清单（不得跳过）

1) **必须使用 `shell_exec` 执行确定性校验**（不要只用自然语言说“已校验”）。

2) **优先校验 `submission.json`**（由 `form-reporter` 落盘）：
   - `email`：必须包含 `@`（建议再做一个最小正则校验）；
   - `quantity`：必须能转成 `int` 且 `>= 1`。

3) **推荐命令（任选其一，避免引用不存在文件）**：

- 方案 A：内联 Python（推荐，最稳定）
  - `argv`: `python -c "<校验代码...>"`
  - 校验代码需要读取 `submission.json` 并在通过时打印 `FORM_OK`。

- 方案 B：调用 workspace 中已存在的脚本
  - `argv`: `python3 validate_input.py <email> <quantity>`
  - 仅当 `validate_input.py` 已存在时才允许使用（不要假设它存在）。

## 禁止事项
- 禁止执行依赖网络的校验。
- 禁止把校验逻辑写进“报告文字”里当作已完成。
