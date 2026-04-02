<div align="center">

[English](README.md) | [中文](README.zh-CN.md)

</div>

# 08_nested_workflow（Workflow 嵌套：Workflow 调 Workflow）

**演示**：Workflow 的 Step 可以调用另一个 Workflow（嵌套编排），并由 Runtime 的递归调度统一执行。

## 前置条件

```bash
pip install -e ".[dev]"
```

## 运行方法

```bash
python examples/08_nested_workflow/run.py
```

预期输出要点：
- `demo_nested_success()`：打印 `status=success`，并展示主流程输出（包含 `call_sub` 与 `publish`）
- `demo_nested_depth_limit()`：打印 `status=failed`，且 `error_type=recursion_limit`

## 学到什么

- “嵌套”不是特殊语法：`Step(capability=CapabilityRef(id="WF-SUB"))` 本质上就是调用另一个 capability id。
- 调度入口统一：所有执行都通过 `CapabilityRuntime._execute()` 递归分发到对应 Adapter。
- 护栏：
  - `ExecutionContext.max_depth` 限制最大嵌套深度（避免无限递归）
  - `LoopStep.max_iterations` + `ExecutionGuards` 限制循环失控（避免爆炸）

## 代码要点（run.py 已实现）

1) 声明并注册两个 Workflow：
- `WF-SUB`：子 workflow（例如 2 个 Step 顺序执行）
- `WF-MAIN`：主 workflow，其中一个 Step 的 capability 指向 `WF-SUB`

2) Adapter 注入：
- `CapabilityKind.WORKFLOW` → `WorkflowAdapter()`
- 被子 workflow 调用到的能力（通常是 Agent/Skill）也要注入对应 Adapter（建议用离线 mock Agent）

3) 断言嵌套输出可追踪：
- 主 workflow 的 `context.step_outputs` 应包含：
  - 主 workflow 自己的 step 输出
  - 嵌套 step 的输出（来自 `WF-SUB` 的最终输出）
- 建议打印 `result.output` 并验证字段结构稳定（便于后续回归对比）

4) 失败形态覆盖（建议）：
- 缺失子 workflow 注册：`validate()` 应返回缺失 ID
- 嵌套过深：触发 `recursion_limit`（通过降低 `RuntimeConfig.max_depth` 或 run 的 `max_depth` 覆盖）
