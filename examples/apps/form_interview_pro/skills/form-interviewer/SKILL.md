---
name: form-interviewer
description: "表单访谈：提出结构化问题并收集答案"
---

# form-interviewer

你负责通过 `request_user_input` 以结构化方式收集字段，并把答案整理为**可落盘的数据结构**，供后续校验与报告使用。

## 必做清单（不得跳过）

1) **一次性收集字段**：必须调用一次 `request_user_input`，并使用稳定的 question_id：
   - `full_name`：姓名（必填）
   - `email`：邮箱（必填）
   - `product`：产品（可给 2~3 个选项，允许自定义）
   - `quantity`：数量（必填，正整数；可给选项 1/2/3）

2) **最小纠错**：
   - 若 `email` 为空或不含 `@`，必须再次提问补齐；
   - 若 `quantity` 不是正整数，必须再次提问补齐。

3) **输出给后续步骤**：
   - 你需要在心智上形成一个 `answers` 字典（键为上面的稳定 id），后续由 `form-reporter` 落盘为 `submission.json`。

## 注意事项
- 不要把“字段收集”仅停留在自然语言里；必须确保字段可被程序校验与落盘。
- 避免重复提问：默认最多 2 轮（首次收集 + 必要纠错）。
