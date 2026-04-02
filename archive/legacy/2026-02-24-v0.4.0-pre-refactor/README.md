<div align="center">

[English](README.md) | [中文](README.zh-CN.md)

</div>

# 2026-02-24 v0.4.0（pre-refactor）完整归档

本目录用于保存 `capability-runtime` 在“统一 Runtime 入口重构”前的完整快照，以便：

- 回归对比（重构前后语义与契约差异）
- 取证追溯（文档/测试/实现三者的对应关系）
- 快速定位重构引入的问题（对照旧入口与旧目录结构）

## 归档范围

按重构输入文档要求，本归档将包含（以当时主线内容为准）：

- `src/capability_runtime/`：旧实现（含 `CapabilityRuntime` 与 `Runtime` 两入口）
- `tests/`：旧离线回归测试
- `docs/`：旧文档集合（不含根目录 `docs_for_coding_agent/`）
- `DOCS_INDEX.md`、`pyproject.toml`：索引与依赖声明快照

## 说明

- 本目录不作为主线实现依赖；仅用于追溯与对照。
- 所有“删除”均遵循：先归档、再从主线移除，并在 `DOCS_INDEX.md` 保持可索引。

