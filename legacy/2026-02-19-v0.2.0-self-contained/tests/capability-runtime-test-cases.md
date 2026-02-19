# Test Cases：Capability-oriented Runtime v0.2.0（系统级）

## Overview

- **Feature**：Capability-oriented Runtime v0.2.0（Skill / Agent / Workflow 三元能力的声明、注册、执行与组合）
- **Requirements Source**：
  - PRD：`docs/prd/agently-skills-runtime-capability-runtime.prd.md`
  - 真相源：`instructcontext/CODEX_PROMPT.md`
  - Engineering Spec v2：`docs/specs/engineering-spec-v2/SPEC_INDEX.md`
- **Last Updated**：2026-02-18

本文件是“测试用例文档”（不是 pytest 代码），用于把需求拆成可执行的 QA 步骤，并作为后续 TDD（RED→GREEN→REFACTOR）的门禁输入。

约束：
- 离线回归必须可跑（不依赖外网/真实 key）。
- `protocol/` 与 `runtime/` 的单测必须不依赖上游包。
- `adapters/` 的测试允许使用 stub/fake/mocking（目标是验证桥接与编排契约，而非复制上游语义）。

---

## Requirements（抽取与编号）

- **REQ-001**：`protocol/capability` 类型可构造（CapabilitySpec/Ref/Result/Status/Kind）。
- **REQ-002**：`ExecutionContext.child()` 递归深度超限抛 `RecursionLimitError`，并包含 call chain 信息。
- **REQ-003**：`ExecutionContext.resolve_mapping()` 支持 6 种表达式形态：`context.*`、`previous.*`、`step.<step_id>.*`、`literal.*`、`item`、`item.*`。
- **REQ-004**：`_deep_get()` 支持 dict 与对象属性的点路径读取；不存在返回 None。
- **REQ-005**：Workflow 协议支持 Step/LoopStep/ParallelStep/ConditionalStep，并可在 WorkflowSpec.steps 中组合。
- **REQ-006**：CapabilityRegistry：register/get/get_or_raise/list_by_kind 可用。
- **REQ-007**：CapabilityRegistry.validate_dependencies() 能检测缺失依赖，且能递归扫描 Workflow 中 nested steps（Parallel/Conditional）。
- **REQ-008**：ExecutionGuards：全局循环总次数熔断（max_total_loop_iterations）超限抛 LoopBreakerError。
- **REQ-009**：LoopController：对 iterate_over 解析得到集合；步骤级 max_iterations + 全局 max_total_loop_iterations 双重限制。
- **REQ-010**：LoopController：单次迭代失败需中止循环，并返回 partial_results + failed_at。
- **REQ-011**：CapabilityRuntime：按 CapabilityKind 分发到 SkillAdapter/AgentAdapter/WorkflowAdapter（Adapter.execute 必须 async）。
- **REQ-012**：WorkflowAdapter：按顺序执行 steps；每步输出写入 context.step_outputs[step.id]；失败即时返回。
- **REQ-013**：ParallelStep：join_strategy 支持 all_success/any_success/best_effort 的最小可回归语义。
- **REQ-014**：ConditionalStep：按 condition_source 解析值选择分支；无匹配走 default。
- **REQ-015**：SkillAdapter：dispatch_rules 按 priority 评估（大者优先）；条件 Phase1 只需支持“context bag key 存在/为真”。
- **REQ-016**：SkillAdapter：source_type 支持 file/inline/uri 的最小加载行为。
- **REQ-017**：AgentAdapter：能把 skills 注入到 agent 任务上下文（测试可用 fake agent/LLM）。
- **REQ-018**：Scenario：Workflow 编排 2 个 Agent + LoopStep（mock LLM/Agent），离线可回归。

---

## 1. Functional Tests

### TC-F-001：CapabilitySpec/Result 可构造
- **Requirement**：REQ-001
- **Priority**：High
- **Preconditions**：无
- **Test Steps**：
  1. 构造 CapabilitySpec（含 id/kind/name）。
  2. 构造 CapabilityResult（含 status=SUCCESS，output 任意）。
- **Expected Results**：
  - 对象可构造；字段存在；默认值符合 spec-v2。

### TC-F-002：ExecutionContext.child() 正常创建子上下文
- **Requirement**：REQ-002
- **Priority**：High
- **Preconditions**：创建 root context，max_depth>=2
- **Test Steps**：
  1. 调用 child("cap-A") 生成子 context。
- **Expected Results**：
  - depth+1；bag 为浅拷贝；call_chain 追加 capability_id。

### TC-F-003：resolve_mapping 读取 context.*
- **Requirement**：REQ-003
- **Priority**：High
- **Preconditions**：context.bag={"task":{"title":"x"}}
- **Test Steps**：
  1. resolve_mapping("context.task.title")
- **Expected Results**：
  - 返回 "x"。

### TC-F-004：resolve_mapping 读取 literal.*
- **Requirement**：REQ-003
- **Priority**：Medium
- **Preconditions**：无
- **Test Steps**：
  1. resolve_mapping("literal.hello")
- **Expected Results**：
  - 返回 "hello"。

### TC-F-005：CapabilityRegistry register/get/list_by_kind
- **Requirement**：REQ-006
- **Priority**：High
- **Preconditions**：创建空 registry
- **Test Steps**：
  1. register 一个 SkillSpec、一个 AgentSpec。
  2. get(id) 获取。
  3. list_by_kind(kind) 过滤。
- **Expected Results**：
  - get 返回对应 spec；list_by_kind 只返回匹配 kind。

### TC-F-006：CapabilityRuntime 分发到不同 Adapter（mock）
- **Requirement**：REQ-011
- **Priority**：High
- **Preconditions**：构造 runtime + registry，注入 fake adapters（每个 adapter 记录被调用次数）
- **Test Steps**：
  1. register SkillSpec/AgentSpec/WorkflowSpec。
  2. await runtime.run("<id>")。
- **Expected Results**：
  - 对应 kind 的 adapter 被调用；返回 CapabilityResult。

### TC-F-007：WorkflowAdapter 顺序执行 + step_outputs 写入
- **Requirement**：REQ-012
- **Priority**：High
- **Preconditions**：WorkflowSpec.steps=[Step(id="s1"...), Step(id="s2"...)]；下游能力用 fake adapter 返回固定 output
- **Test Steps**：
  1. await runtime.run("wf")
- **Expected Results**：
  - context.step_outputs["s1"], ["s2"] 存在且为对应结果。

---

## 2. Edge Case Tests

### TC-E-001：ExecutionContext.child() 达到 max_depth 边界仍可创建
- **Requirement**：REQ-002
- **Priority**：High
- **Preconditions**：root.depth=0,max_depth=1
- **Test Steps**：
  1. child("cap-A")
- **Expected Results**：
  - 成功创建（depth==1）。

### TC-E-002：resolve_mapping previous.* 在无 step_outputs 时返回 None
- **Requirement**：REQ-003
- **Priority**：Medium
- **Preconditions**：context.step_outputs 为空
- **Test Steps**：
  1. resolve_mapping("previous.any")
- **Expected Results**：
  - 返回 None。

### TC-E-003：resolve_mapping step.<id>.* 指向不存在 step_id 返回 None
- **Requirement**：REQ-003
- **Priority**：Medium
- **Preconditions**：step_outputs 无该 step
- **Test Steps**：
  1. resolve_mapping("step.unknown.x")
- **Expected Results**：
  - 返回 None。

### TC-E-004：_deep_get 支持对象属性读取
- **Requirement**：REQ-004
- **Priority**：Low
- **Preconditions**：bag 中放入带属性的对象
- **Test Steps**：
  1. resolve_mapping("context.obj.attr")
- **Expected Results**：
  - 返回 attr 值。

### TC-E-005：LoopController max_iterations 取 min(步骤级, 全局)
- **Requirement**：REQ-009
- **Priority**：High
- **Preconditions**：集合长度大于步骤级 max_iterations
- **Test Steps**：
  1. 执行 LoopStep
- **Expected Results**：
  - 抛出或返回失败（以 spec-v2 为准），并包含可诊断信息。

---

## 3. Error Handling Tests

### TC-ERR-001：child() 超限抛 RecursionLimitError
- **Requirement**：REQ-002
- **Priority**：High
- **Preconditions**：root.depth=0,max_depth=0
- **Test Steps**：
  1. 调用 child("cap-A")
- **Expected Results**：
  - 抛 RecursionLimitError。

### TC-ERR-002：resolve_mapping 未知前缀抛 ValueError
- **Requirement**：REQ-003
- **Priority**：High
- **Preconditions**：无
- **Test Steps**：
  1. resolve_mapping("unknown.x")
- **Expected Results**：
  - 抛 ValueError，包含 unknown 前缀。

### TC-ERR-003：validate_dependencies 检测缺失 Skill 依赖
- **Requirement**：REQ-007
- **Priority**：High
- **Preconditions**：register 一个 AgentSpec.skills=["missing-skill"]
- **Test Steps**：
  1. validate_dependencies
- **Expected Results**：
  - 返回包含缺失依赖的错误列表。

### TC-ERR-004：validate_dependencies 检测 Workflow nested steps 缺失能力
- **Requirement**：REQ-007
- **Priority**：High
- **Preconditions**：WorkflowSpec 内含 ParallelStep/ConditionalStep 分支引用未注册 capability
- **Test Steps**：
  1. validate_dependencies
- **Expected Results**：
  - 能递归发现缺失引用。

### TC-ERR-005：ExecutionGuards 超 max_total_loop_iterations 抛 LoopBreakerError
- **Requirement**：REQ-008
- **Priority**：High
- **Preconditions**：max_total_loop_iterations 很小
- **Test Steps**：
  1. 连续 record_loop_iteration 超限
- **Expected Results**：
  - 抛 LoopBreakerError。

### TC-ERR-006：LoopController 迭代中某次失败中止并返回 partial
- **Requirement**：REQ-010
- **Priority**：High
- **Preconditions**：fake executor 在第 N 次返回 FAILED
- **Test Steps**：
  1. 执行 LoopStep
- **Expected Results**：
  - 返回结果包含 partial_results 与 failed_at。

---

## 4. State Transition Tests

### TC-ST-001：ParallelStep join_strategy=all_success
- **Requirement**：REQ-013
- **Priority**：Medium
- **Preconditions**：两分支分别成功/失败
- **Test Steps**：
  1. 执行 ParallelStep
- **Expected Results**：
  - 只要有失败则整体失败。

### TC-ST-002：ParallelStep join_strategy=any_success
- **Requirement**：REQ-013
- **Priority**：Medium
- **Preconditions**：两分支一成功一失败
- **Test Steps**：
  1. 执行 ParallelStep
- **Expected Results**：
  - 整体成功（并记录成功分支输出）。

### TC-ST-003：ParallelStep join_strategy=best_effort
- **Requirement**：REQ-013
- **Priority**：Low
- **Preconditions**：两分支一成功一失败
- **Test Steps**：
  1. 执行 ParallelStep
- **Expected Results**：
  - 整体成功并返回可用输出（失败分支可记录 error）。

### TC-ST-004：ConditionalStep 分支选择 + default
- **Requirement**：REQ-014
- **Priority**：Medium
- **Preconditions**：condition_source 解析出值不在 branches
- **Test Steps**：
  1. 执行 ConditionalStep
- **Expected Results**：
  - 走 default 分支。

### TC-ST-005：Scenario：Workflow 编排 2 Agent + LoopStep（mock）
- **Requirement**：REQ-018
- **Priority**：High
- **Preconditions**：两个 AgentSpec + 一个 WorkflowSpec（含 Step + LoopStep）；AgentAdapter 用 fake，不触网
- **Test Steps**：
  1. register 三个 spec
  2. runtime.validate()
  3. await runtime.run("wf-main", context_bag={"task":"x"})
- **Expected Results**：
  - status=SUCCESS
  - output 包含 collect_as 对应的 results 数组

---

## Test Coverage Matrix

| Requirement ID | Planned pytest file (CODEX_PROMPT Step5) | Test Cases |
|---|---|---|
| REQ-001 | `tests/protocol/test_capability.py` | TC-F-001 |
| REQ-002 | `tests/protocol/test_context.py` | TC-F-002, TC-E-001, TC-ERR-001 |
| REQ-003 | `tests/protocol/test_context.py` | TC-F-003, TC-F-004, TC-E-002, TC-E-003, TC-ERR-002 |
| REQ-004 | `tests/protocol/test_context.py` | TC-E-004 |
| REQ-005 | `tests/protocol/test_workflow.py` |（协议结构用例，后续补齐） |
| REQ-006 | `tests/runtime/test_registry.py` | TC-F-005 |
| REQ-007 | `tests/runtime/test_registry.py` | TC-ERR-003, TC-ERR-004 |
| REQ-008 | `tests/runtime/test_guards.py` | TC-ERR-005 |
| REQ-009 | `tests/runtime/test_loop.py` | TC-E-005 |
| REQ-010 | `tests/runtime/test_loop.py` | TC-ERR-006 |
| REQ-011 | `tests/runtime/test_engine.py` | TC-F-006 |
| REQ-012 | `tests/adapters/test_workflow_adapter.py` | TC-F-007 |
| REQ-013 | `tests/adapters/test_workflow_adapter.py` | TC-ST-001, TC-ST-002, TC-ST-003 |
| REQ-014 | `tests/adapters/test_workflow_adapter.py` | TC-ST-004 |
| REQ-018 | `tests/scenarios/test_workflow_with_loop.py` | TC-ST-005 |

备注：本矩阵只映射本轮 v0.2.0 的主线需求；旧 bridge-only 的测试将按 `docs/specs/engineering-spec-v2/06_Implementation/MIGRATION.md` 归档到 `legacy/`。

