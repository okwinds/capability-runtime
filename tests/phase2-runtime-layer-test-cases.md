# Test Cases：Phase 2 — Runtime Layer（系统/场景）

## Overview

- **Feature**：Runtime 层（Registry + Guards + Loop + Engine）+ 包级导出面更新 + Runtime 单测
- **Requirements Source**：
  - Phase 2 指令（真相源）：`instructcontext/4-true-codex-phase2-runtime-layer.md`
  - Phase 2 工程规格：`docs/specs/phases/phase2-runtime-layer.md`
- **Last Updated**：2026-02-19

本文件是 Phase 2 的“手工/场景测试用例文档”，用于在实现阶段提供可操作的验收步骤与 Coverage Matrix。覆盖范围包含：

- Functional（主流程）
- Edge（边界条件）
- Error（错误处理）
- State Transition（运行状态演进：guards/context/递归调度等）

> 说明：本文件是测试规格（Test Spec）。实现落地后，关键用例应沉淀为 `tests/runtime/*` 的离线单测，并在 worklog 记录回归命令与结果。

---

## 1. Functional Tests

### TC-F-001：Runtime 目录与模块清单齐备
- **Requirement**：AC-P2-001
- **Priority**：High
- **Preconditions**：已按 Phase 2 新增 `src/agently_skills_runtime/runtime/`
- **Test Steps**：
  1. 执行：
     - `ls src/agently_skills_runtime/runtime`
- **Expected Results**：
  - 至少包含：`__init__.py`、`guards.py`、`registry.py`、`loop.py`、`engine.py`

### TC-F-002：`ExecutionGuards` 行为正确（tick/counter/reset）
- **Requirement**：AC-P2-004, AC-P2-008
- **Priority**：High
- **Preconditions**：已生成 `tests/runtime/test_guards.py`
- **Test Steps**：
  1. 运行 `PATH=.venv/bin:$PATH python -m pytest tests/runtime/test_guards.py -v`
- **Expected Results**：
  - 测试通过
  - 覆盖点至少包含：
    - `tick()` 递增 `counter`
    - “恰好等于上限不抛异常”
    - “超过上限抛 `LoopBreakerError`”
    - `reset()` 将 `counter` 归零

### TC-F-003：`CapabilityRegistry` CRUD 与 list_by_kind 行为正确
- **Requirement**：AC-P2-003, AC-P2-008
- **Priority**：High
- **Preconditions**：已生成 `tests/runtime/test_registry.py`
- **Test Steps**：
  1. 运行 `PATH=.venv/bin:$PATH python -m pytest tests/runtime/test_registry.py -v -k \"CRUD or list_by_kind\"`
- **Expected Results**：
  - 测试通过
  - 覆盖点至少包含：
    - register/get/get_or_raise
    - last-write-wins 覆盖策略
    - list_all/list_ids/has/unregister
    - list_by_kind 过滤准确

### TC-F-004：`CapabilityRegistry.validate_dependencies` 覆盖三类依赖来源
- **Requirement**：AC-P2-003, AC-P2-008
- **Priority**：High
- **Preconditions**：同上
- **Test Steps**：
  1. 运行 `PATH=.venv/bin:$PATH python -m pytest tests/runtime/test_registry.py -v -k validate_dependencies`
- **Expected Results**：
  - 测试通过
  - 缺失依赖 ID 以排序后的列表返回
  - 覆盖点至少包含：
    - `AgentSpec.skills`（缺 skill）
    - `AgentSpec.collaborators/callable_workflows`（缺 capability）
    - `WorkflowSpec.steps`（Step/LoopStep/ParallelStep/ConditionalStep）
    - `SkillSpec.dispatch_rules[*].target.id`

### TC-F-005：`LoopController.run_loop` 主流程（SUCCESS + effective_max）
- **Requirement**：AC-P2-005, AC-P2-008
- **Priority**：High
- **Preconditions**：已生成 `tests/runtime/test_loop.py`
- **Test Steps**：
  1. 运行 `PATH=.venv/bin:$PATH python -m pytest tests/runtime/test_loop.py -v -k \"normal_loop or max_iterations\"`
- **Expected Results**：
  - 测试通过
  - `max_iterations > len(items)` 时仍只处理全部 items（由 `effective_max` 控制）
  - `metadata` 至少包含 `completed_iterations` 与 `total_planned`

### TC-F-006：`CapabilityRuntime.run` 能正确分发到 Adapter 并填充 duration_ms
- **Requirement**：AC-P2-006, AC-P2-008
- **Priority**：High
- **Preconditions**：已生成 `tests/runtime/test_engine.py`
- **Test Steps**：
  1. 运行 `PATH=.venv/bin:$PATH python -m pytest tests/runtime/test_engine.py -v -k dispatches_to_adapter`
- **Expected Results**：
  - 测试通过
  - `CapabilityResult.status == success`
  - `duration_ms` 被填充且 `> 0`

### TC-F-007：包级导出面可一次性导入（Runtime）
- **Requirement**：AC-P2-007
- **Priority**：High
- **Preconditions**：已按 Phase 2 更新 `src/agently_skills_runtime/__init__.py`
- **Test Steps**：
  1. 执行 Phase 2 spec 的“导入面验收” `python -c` 片段（见 `docs/specs/phases/phase2-runtime-layer.md` Test Plan 5.4）
- **Expected Results**：
  - 输出包含 `Runtime imports OK`

---

## 2. Edge Case Tests

### TC-E-001：`LoopController` 支持空 items（返回 SUCCESS + 空 output）
- **Requirement**：AC-P2-005, AC-P2-008
- **Priority**：Medium
- **Preconditions**：已生成 `tests/runtime/test_loop.py`
- **Test Steps**：
  1. 运行 `PATH=.venv/bin:$PATH python -m pytest tests/runtime/test_loop.py -v -k empty_items`
- **Expected Results**：
  - 测试通过
  - `status == success` 且 `output == []`

### TC-E-002：`CapabilityRegistry.get` 未命中返回 None
- **Requirement**：AC-P2-003, AC-P2-008
- **Priority**：Low
- **Preconditions**：已生成 `tests/runtime/test_registry.py`
- **Test Steps**：
  1. 运行 `PATH=.venv/bin:$PATH python -m pytest tests/runtime/test_registry.py -v -k get_nonexistent`
- **Expected Results**：
  - 测试通过（返回 `None`）

---

## 3. Error Handling Tests

### TC-ERR-001：Runtime 层不得 import agently/agent_sdk（静态检查）
- **Requirement**：AC-P2-002
- **Priority**：High
- **Preconditions**：Runtime 代码已生成
- **Test Steps**：
  1. 执行：
     - `grep -r \"import agently\" src/agently_skills_runtime/runtime/ && echo FAIL || echo OK`
     - `grep -r \"import agent_sdk\" src/agently_skills_runtime/runtime/ && echo FAIL || echo OK`
- **Expected Results**：
  - 两条命令都输出 `OK`（未发现 import）

### TC-ERR-002：`CapabilityRuntime.run` 找不到 capability 时返回 FAILED（error_type=not_found）
- **Requirement**：AC-P2-006, AC-P2-008
- **Priority**：High
- **Preconditions**：已生成 `tests/runtime/test_engine.py`
- **Test Steps**：
  1. 运行 `PATH=.venv/bin:$PATH python -m pytest tests/runtime/test_engine.py -v -k run_not_found`
- **Expected Results**：
  - 测试通过
  - 返回 `FAILED`
  - 错误信息包含 `not found`（或等价）

### TC-ERR-003：未注册 Adapter 时返回 FAILED（error_type=no_adapter）
- **Requirement**：AC-P2-006, AC-P2-008
- **Priority**：High
- **Preconditions**：同上
- **Test Steps**：
  1. 运行 `PATH=.venv/bin:$PATH python -m pytest tests/runtime/test_engine.py -v -k run_no_adapter`
- **Expected Results**：
  - 测试通过
  - 返回 `FAILED`
  - 错误信息包含 `no adapter`（或等价）

### TC-ERR-004：Adapter 抛异常时返回 FAILED（error_type=adapter_error）
- **Requirement**：AC-P2-006, AC-P2-008
- **Priority**：High
- **Preconditions**：同上
- **Test Steps**：
  1. 运行 `PATH=.venv/bin:$PATH python -m pytest tests/runtime/test_engine.py -v -k run_adapter_exception`
- **Expected Results**：
  - 测试通过
  - 返回 `FAILED`
  - 错误信息包含异常信息（例如 `unexpected boom`）

### TC-ERR-005：递归超限时返回 FAILED（error_type=recursion_limit）
- **Requirement**：AC-P2-006, AC-P2-008
- **Priority**：High
- **Preconditions**：同上
- **Test Steps**：
  1. 运行 `PATH=.venv/bin:$PATH python -m pytest tests/runtime/test_engine.py -v -k run_recursion_limit`
- **Expected Results**：
  - 测试通过
  - 返回 `FAILED`
  - 错误信息包含 `recursion` / `depth`（或等价）

---

## 4. State Transition Tests

### TC-ST-001：每次顶层 run 都会 reset guards（计数不跨 run 累积）
- **Requirement**：AC-P2-006, AC-P2-008
- **Priority**：High
- **Preconditions**：已生成 `tests/runtime/test_engine.py`
- **Test Steps**：
  1. 运行 `PATH=.venv/bin:$PATH python -m pytest tests/runtime/test_engine.py -v -k guards_reset_each_run`
- **Expected Results**：
  - 测试通过
  - 两次 `run` 的结果均成功，且第二次 `run` 前计数被重置（不叠加到第一次）

### TC-ST-002：Loop 中全局熔断可触发（LoopBreakerError）
- **Requirement**：AC-P2-004, AC-P2-005, AC-P2-008
- **Priority**：Medium
- **Preconditions**：已生成 `tests/runtime/test_loop.py`
- **Test Steps**：
  1. 运行 `PATH=.venv/bin:$PATH python -m pytest tests/runtime/test_loop.py -v -k global_guards_breaker`
- **Expected Results**：
  - 测试通过
  - 超过 `max_total_loop_iterations` 时抛 `LoopBreakerError`

---

## 5. Test Coverage Matrix

| Requirement ID | Test Cases | Coverage Status |
|---|---|---|
| AC-P2-001 | TC-F-001 | ✓ Complete（规格层） |
| AC-P2-002 | TC-ERR-001 | ✓ Complete（规格层） |
| AC-P2-003 | TC-F-003, TC-F-004, TC-E-002 | ✓ Complete（规格层） |
| AC-P2-004 | TC-F-002, TC-ST-002 | ✓ Complete（规格层） |
| AC-P2-005 | TC-F-005, TC-E-001, TC-ST-002 | ✓ Complete（规格层） |
| AC-P2-006 | TC-F-006, TC-ERR-002, TC-ERR-003, TC-ERR-004, TC-ERR-005, TC-ST-001 | ✓ Complete（规格层） |
| AC-P2-007 | TC-F-007 | ✓ Complete（规格层） |
| AC-P2-008 | TC-F-002, TC-F-003, TC-F-004, TC-F-005, TC-F-006, TC-ERR-002, TC-ERR-003, TC-ERR-004, TC-ERR-005, TC-ST-001, TC-ST-002 | ✓ Complete（规格层） |
| AC-P2-009 | TC-F-001, TC-F-007 | ◐ Partial（实现阶段补充“diff/约束核对证据”更佳） |
