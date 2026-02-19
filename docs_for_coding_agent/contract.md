# 编码任务契约：使用 agently-skills-runtime 的标准流程

本文是编码智能体在本仓执行任务时的默认行为约束。
目标：减少偏航、保证可复现、避免绕过运行时。

## 收到任务后的标准流程

1. 先读 `docs_for_coding_agent/cheatsheet.md`，建立 API 心智模型。
2. 根据任务类型选择参考入口：
   - 定义 Agent：`examples/11_agent_domain_starter/agents/`
   - 编排 Workflow：`examples/02_workflow_sequential` 到 `examples/05_workflow_conditional`
   - 真实接线：`examples/10_bridge_wiring/`
   - 构建业务域：`docs_for_coding_agent/04-agent-domain-guide.md`
3. 按最小改动实现。
4. 补充或更新测试（至少离线回归）。
5. 运行验证：`python -m pytest tests/ -v`。

## 能力声明检查清单

- [ ] `CapabilitySpec.id` 全局唯一。
- [ ] `CapabilitySpec.kind` 与声明类型一致（skill/agent/workflow）。
- [ ] `AgentSpec` 在 `LoopStep` 中使用时设置 `loop_compatible=True`。
- [ ] `WorkflowSpec` 中每个 `CapabilityRef.id` 都已注册。
- [ ] `InputMapping.source` 使用合法前缀。
- [ ] `LoopStep.iterate_over` 指向列表来源。
- [ ] 注册后执行 `runtime.validate()` 并断言结果为空。

## Workflow 编排检查清单

- [ ] 每个 Step ID 唯一。
- [ ] 数据流可追踪（无悬空 `step.*` 引用）。
- [ ] `LoopStep.max_iterations` 合理。
- [ ] 嵌套深度不超过 `RuntimeConfig.max_depth`。
- [ ] `output_mappings` 覆盖业务最终需要字段。
- [ ] 错误路径可观测（失败时返回明确 error）。

## 输入映射约束（必须精确）

支持前缀：
- `context.{key}`
- `previous.{key}`
- `step.{step_id}.{key}`
- `step.{step_id}`
- `literal.{value}`
- `item` / `item.{key}`

注意：`resolve_mapping()` 找不到字段时返回 `None`，不会抛异常。
因此拼写错误会表现为“静默空值”，必须通过测试覆盖发现。

## 常见错误与修复

| 错误现象 | 可能原因 | 修复动作 |
|---|---|---|
| `Capability not found: X` | X 未注册 | 检查 `register_all()` 是否包含 X |
| `No adapter registered for kind` | 未注入对应 Adapter | 在 runtime 中 `set_adapter(kind, adapter)` |
| `Recursion depth N exceeds max M` | 嵌套过深 | 降低嵌套层级或调大 `max_depth` |
| `LoopStep ... expected list` | `iterate_over` 不是列表 | 校验上游输出字段名和类型 |
| 输入字段是 `None` | `InputMapping.source` 写错 | 核对 source 前缀和 step_id |
| 全局循环熔断 | 总循环次数超过上限 | 缩小输入规模或调低迭代路径 |
| real 模式直接崩溃 | 缺 `.env` / 缺依赖门禁 | 加入提示并安全退出（exit 0） |

## 绝对禁止

- ❌ 在业务代码中绕过 Runtime 直接串联执行链。
- ❌ 在 Workflow Adapter 之外手写递归调度。
- ❌ 在 protocol 层引入上游 SDK 依赖。
- ❌ 跳过 `validate()` 直接上线。
- ❌ 无需求时改动 `src/agently_skills_runtime/` 核心实现。
- ❌ 在代码或文档中写入真实密钥。
- ❌ 用 `as any` / `@ts-ignore` / 静默吞错掩盖问题。

## 推荐执行顺序（最小风险）

1. 先写 `Spec`（Goal / AC / Test Plan）。
2. 先跑或补离线测试（RED）。
3. 实现最小改动（GREEN）。
4. 执行全量回归并记录命令输出。
5. 更新 `worklog`、`task summary`、`DOCS_INDEX.md`。

## 验收出口

满足以下条件才视为“任务完成”：
- 目标能力可运行（至少 mock 模式）。
- 离线回归通过。
- 关键文档已登记并可追溯。
- 未破坏现有 public API 行为。

若以上任一项不满足，任务状态应保持为“未完成”。
