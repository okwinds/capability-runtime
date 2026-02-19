# 公共 API（Public API, v2）

> 目标：锁定对外导出清单与版本策略，避免实现阶段“入口漂移”。

## 1) 对外导出清单（以 v0.2.0 为目标）

以 `instructcontext/CODEX_PROMPT.md` 的 `__init__.py` 为准，对外导出分组如下：

### Protocol

- `CapabilitySpec`
- `CapabilityKind`
- `CapabilityRef`
- `CapabilityResult`
- `CapabilityStatus`
- `SkillSpec`
- `SkillDispatchRule`
- `AgentSpec`
- `AgentIOSchema`
- `WorkflowSpec`
- `Step`
- `LoopStep`
- `ParallelStep`
- `ConditionalStep`
- `InputMapping`
- `WorkflowStep`
- `ExecutionContext`
- `RecursionLimitError`

### Runtime

- `CapabilityRuntime`
- `RuntimeConfig`
- `CapabilityRegistry`
- `LoopBreakerError`

## 2) 版本策略（Versioning）

- 目标版本：`0.2.0`（破坏式升级）。
- 语义化版本（SemVer）口径：
  - `0.x` 阶段允许破坏式升级，但必须在 `docs/specs/engineering-spec-v2/06_Implementation/MIGRATION.md` 明确说明破坏点与迁移路径。
  - 对外导出清单是“可测试的契约”：实现阶段需增加导入回归用例（见 `05_Testing/TRACEABILITY.md`）。

## 3) 向后兼容声明（Compatibility Statement）

- v0.2.0 新主线不承诺兼容旧 bridge-only API（例如旧 `AgentlySkillsRuntime` 入口）。
- 旧 API/实现被归档到 `legacy/`，用于追溯与必要时的回滚参考，但不作为新主线支持面的一部分。

## 4) 假设（Assumptions）

- 若实现阶段需要新增对外导出，必须先更新本文件与 requirements/test traceability，再写代码（Doc/Spec First）。

