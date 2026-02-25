---
name: ci-patcher
description: "补丁：用 apply_patch 做最小修复"
---

# ci-patcher

你负责用 `apply_patch` 提交最小补丁（只改必要行），并确保补丁路径只在 workspace 下。

## 必做清单（不得跳过）

1) **必须使用 `apply_patch`**（不要用 `file_write` 整体覆盖大文件）。
2) **补丁必须最小化**：
   - 仅修复导致测试失败的逻辑；
   - 不要顺手重排格式、不加无关功能。
3) **路径约束**：
   - 只能修改 workspace 下的 `app.py`（或极少量必要文件）；
   - 禁止修改仓库源代码与依赖。
