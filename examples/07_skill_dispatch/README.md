# 07_skill_dispatch（Skill 调度：dispatch_rules）

**演示**：通过 `SkillSpec.dispatch_rules` 让 Skill 在执行时“主动调度”其他能力（Agent/Workflow/Skill）。

## 前置条件

```bash
pip install -e ".[dev]"
```

## 运行方法

```bash
python examples/07_skill_dispatch/run.py
```

预期输出要点：
- Case 1（未提供 `context_bag.analyze`）：`metadata.dispatched` 为空/`null`
- Case 2（提供 `context_bag.analyze=true`）：`metadata.dispatched` 含 1 条调度结果

## 地面真相（必须对齐）

### 1) `condition` 不是表达式语言

当前 `SkillDispatchRule.condition` 的语义是：
- 把 `condition` 当作 **context bag 的 key**
- 用 `bool(context.bag.get(condition))` 判断是否触发

这意味着：
- ✅ 你需要通过 `CapabilityRuntime.run(..., context_bag={...})` 提供该 key
- ❌ 仅把 key 放在 `input` 里不一定能触发（SkillAdapter 不会把 `input` 合并进 `context.bag`）

### 2) 调度结果记录在 `metadata`

当规则命中并完成调度后：
- `CapabilityResult.output` 仍然是 Skill 内容（`str`）
- 调度的副结果写入 `CapabilityResult.metadata["dispatched"]`

## 代码要点（run.py 已实现）

1) 注册两类能力：
- 被执行的 Skill：包含至少 1 条 `dispatch_rules`
- 被调度的目标能力：建议用一个**离线 mock Agent**（避免依赖真实 LLM）

2) 触发两次运行：
- 第一次：`context_bag` 不提供 condition key → 不应触发调度（`metadata` 为空或不含 dispatched）
- 第二次：`context_bag` 提供 condition key 且 truthy → 应触发调度，并在 metadata 里出现目标能力输出摘要

3) 输出建议（便于人工验证）：
- 打印 Skill 的 `result.output`（内容）与 `result.metadata`（调度记录）
- 打印被调度能力的输出摘要（来自 `metadata["dispatched"]`）
