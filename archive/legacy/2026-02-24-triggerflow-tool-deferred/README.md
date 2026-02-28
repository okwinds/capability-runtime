# 2026-02-24 TriggerFlow tool 桥接（triggerflow_run_flow）搁置归档

本目录用于归档并追溯“TriggerFlow 作为 SDK Agent tool（`triggerflow_run_flow`）”的桥接实现与对应测试。

依据：
- 输入文档 `docs/context/refactoring-spec.md` 的 **2.5 关于 TriggerFlow 的决策**：明确“搁置 TriggerFlow 工具桥接”，推荐改为 **TriggerFlow 顶层编排多个 `Runtime.run()`** 的路径。

归档原因（简述）：
- 将 TriggerFlow 作为 SDK Agent 的 tool 会形成“Agent tool loop → 再触发完整 flow → flow 内再触发 Agent”的嵌套闭环，调试与审计复杂度显著上升；
- 本仓当前阶段以“生产级统一 Runtime 基座”为主旨，优先收敛协议与证据链闭环；TriggerFlow tool 桥接不阻塞主线能力闭环，因此按规格暂缓。

## 归档映射（原路径 → 现路径）

- `src/capability_runtime/adapters/triggerflow_tool.py`
  → `archive/legacy/2026-02-24-triggerflow-tool-deferred/src/capability_runtime/adapters/triggerflow_tool.py`
- `tests/test_triggerflow_tool.py`
  → `archive/legacy/2026-02-24-triggerflow-tool-deferred/tests/test_triggerflow_tool.py`

## 恢复提示（未来如需启用）

若未来决定重新启用 TriggerFlow tool 桥接，应遵循：
- 先在 spec 中重新声明“为什么需要路径 A（tool）而不是路径 B（顶层编排）”，并给出审计/回滚策略；
- 再将归档实现移回主线，并补齐 bridge 模式下的 NodeReport/事件证据链护栏测试。

