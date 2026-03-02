# archive/（历史归档）

本目录用于存放**建设过程中的历史产物**，以便追溯与审计，但不应影响“框架本身”的阅读与使用。

## 如何使用（推荐）

1) 先读主线入口（当前有效口径）：
- `README.md`
- `DOCS_INDEX.md`

2) 再从本目录按需追溯历史材料：
- 如果你在排查“为什么当时这么做/为什么后来改了”，优先看 `archive/docs/`（文档与指令上下文归档包）
- 如果你在对照旧示例/旧入口行为，优先看 `archive/examples-legacy/`
- 如果你在对照重构前的快照基线，优先看 `archive/legacy/` 中的快照目录

## 归档内容（分类）

- `archive/docs/`
  - 文档与指令上下文归档包（将建设过程中的文档材料从主线移出，保留对照与可追溯入口）。
  - 其中部分归档包包含早期“指令/上下文素材”（例如：`archive/docs/2026-02-24-unified-runtime-refactor/archive/instructcontext/`），用于追溯“为何这样设计/实现”。
- `archive/examples-legacy/`
  - `examples/` 的对照示例归档（多数基于旧入口/旧叙事；主线不保证可运行）。
- `archive/legacy/`
  - 历史分支/实验线/阶段性产物归档（可能包含旧规格、旧实现思路、阶段性自检材料等）。
- `archive/projects/`
  - 参考应用/原型项目（用于验证或演示全量能力，不属于 runtime 框架主线交付物）。

## 常用追溯入口（索引）

- 文档与指令上下文归档包：
  - `archive/docs/2026-02-24-unified-runtime-refactor/README.md`
- 对照示例归档入口：
  - `archive/examples-legacy/README.md`
- 重构前快照基线（对照用）：
  - `archive/legacy/2026-02-24-v0.4.0-pre-refactor/README.md`
- 搁置决策归档（对照用）：
  - `archive/legacy/2026-02-24-triggerflow-tool-deferred/README.md`

## 备注

- 框架主线代码位于 `src/`，离线回归测试位于 `tests/`（本次结项清理不改动任何一行）。
