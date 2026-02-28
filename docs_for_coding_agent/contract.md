# 编码任务契约：使用 capability-runtime 的标准流程（统一 Runtime）

本文是编码智能体在本仓执行任务时的默认行为约束，目标是：

- 不偏航：所有改动服务于“生产级能力运行时基座”的主旨
- 可回归：变更必须可测试、可复现
- 可追溯：关键命令/结论写入 `docs/internal/worklog.md`

## 1) 最小闭环（你每次都应该走）

1. 读输入文档（若本轮提供）：明确边界、验收与禁止项
2. 写/更新 spec（至少 Goal/AC/Test Plan）
3. 先补离线回归测试（RED）
4. 实现最小改动（GREEN）
5. 跑离线回归（至少 `python -m pytest tests/ -q`）
6. 更新：`docs/internal/worklog.md`、`DOCS_INDEX.md`、（必要时）任务总结

> 约束提示：所有“删除”必须先归档并保持可索引追溯；未经授权不得修改 `.gitignore`。

## 2) Runtime 使用契约（单一入口）

### 2.1 执行入口

- 非流式：`await Runtime.run(capability_id, input=..., context=...)`
- 流式：`async for x in Runtime.run_stream(...): ...`

### 2.2 运行前必须校验

- `Runtime.register(...)` / `Runtime.register_many(...)`
- `missing = Runtime.validate()`
  - `missing` 非空：视为配置/注册问题，先补齐依赖再执行（不要“带病运行”）

## 3) 能力声明检查清单（Protocol）

- [ ] `CapabilitySpec.id` 全局唯一
- [ ] `CapabilitySpec.kind` 与声明一致（仅 `AGENT` / `WORKFLOW`）
- [ ] `WorkflowSpec` 中每个 `CapabilityRef.id` 都已注册
- [ ] `InputMapping.source` 使用合法前缀：`context.*` / `previous.*` / `step.*` / `item.*` / `literal.*`
- [ ] 注册完成后执行 `Runtime.validate()` 并断言为空

## 4) 编排（Workflow）检查清单

- [ ] 每个 step 的 `id` 唯一
- [ ] 数据流可追踪：避免悬空 `step.xxx` 引用
- [ ] `LoopStep.iterate_over` 必须解析为 `list`（否则 LoopStep 失败）
- [ ] 嵌套深度不超过 `RuntimeConfig.max_depth`（默认 10）

## 5) 常见错误与最短排查路径

| 现象 | 常见原因 | 最短修复 |
|---|---|---|
| `Capability not found: X` | X 未注册 | 补注册 + `validate()` 断言为空 |
| `... recursion depth ...` | 嵌套过深 | 减少嵌套或调小输入规模（必要时调大 `max_depth` 并补测试） |
| 映射字段是 `None` | `InputMapping.source` 拼写错 | 打印解析结果 + 为该映射补回归测试 |
| 想调用 TriggerFlow tool | 该路径已搁置归档 | 用 TriggerFlow 顶层编排多个 `Runtime.run()` |

## 6) 绝对禁止

- ❌ 在 protocol 层引入上游依赖（破坏可审计边界）
- ❌ 绕过 Runtime 手写递归调度/编排（会造成语义分叉）
- ❌ 把业务域名词/规则写死进 runtime（本仓不定义业务）
- ❌ 在代码或文档中提交真实密钥（使用 `.env.example` 描述配置项）
