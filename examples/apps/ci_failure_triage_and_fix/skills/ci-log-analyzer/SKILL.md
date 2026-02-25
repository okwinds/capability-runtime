---
name: ci-log-analyzer
description: "CI 排障：复现失败并总结原因"
---

# ci-log-analyzer

你负责“复现失败 → 锁定最小修复点”。

## 必做清单（不得跳过）

1) **必须先复现失败**：
   - 使用 `shell_exec` 在 workspace 根目录运行测试（推荐：`python -m pytest -q test_app.py`）。
   - 若测试未失败，不要直接开始修复；应检查当前 workspace 是否包含“失败基线”（`app.py`/`test_app.py`）。

2) **提炼最小修复点**：
   - 只关注导致失败的最小函数/最小差异（避免重写整个文件）。

## 禁止事项
- 禁止“从零重写一个全通过项目”来规避失败（这会破坏示例的教学目的）。
- 禁止引入外部依赖或访问网络。
