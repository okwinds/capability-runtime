<div align="center">

[English](README.md) | [中文](README.zh-CN.md)

</div>

# Legacy Archive：2026-02-13 repo-structure-cleanup

本目录用于归档“与当前桥接主线无关/已不再使用”的历史资产，保留可追溯性但不干扰主线阅读。

## 本次归档内容

- `_path.py`
  - 说明：历史上的测试辅助 shim（把 `src/` 注入 `sys.path`）。
  - 归档原因：当前测试已通过 `tests/conftest.py` 解决 import 路径问题，仓库内不再引用该文件。

