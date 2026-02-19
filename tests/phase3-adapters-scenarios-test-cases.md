# Test Cases：Phase 3 — Adapters + Scenarios（系统/场景）

## Overview

- **Feature**：Adapter 层（AgentAdapter / WorkflowAdapter / SkillAdapter）+ 场景回归（WF-001D / Nested Workflow）+ 版本 `0.4.0`
- **Requirements Source**：
  - Phase 3 指令（真相源）：`instructcontext/4-true-codex-phase3-adapters-scenarios.md`
  - Phase 3 工程规格：`docs/specs/phases/phase3-adapters-scenarios.md`
- **Last Updated**：2026-02-19

本文件是 Phase 3 的“手工/场景测试用例文档”，用于在实现阶段提供可操作的验收步骤与 Coverage Matrix。实现落地后，关键用例应沉淀为 `tests/adapters/*` 与 `tests/scenarios/*` 的离线回归测试，并在 worklog 记录命令与结果。

> 说明：本阶段测试全部使用 mock，不依赖真实 LLM、真实上游 SDK 或网络。

---

## 1. Functional Tests

### TC-F-001：Adapter 文件清单齐备 + 导出面更新

- **Requirement**：AC-P3-001
- **Priority**：High
- **Test Steps**：
  1. `ls src/agently_skills_runtime/adapters`
  2. `PATH=.venv/bin:$PATH python -c "from agently_skills_runtime import AgentAdapter, WorkflowAdapter, SkillAdapter; print('Adapters imports OK')"`
- **Expected Results**：
  - 目录包含：`agent_adapter.py` / `workflow_adapter.py` / `skill_adapter.py`
  - 导入成功，输出包含 `Adapters imports OK`

### TC-F-002：AgentAdapter 基础执行（mock runner）

- **Requirement**：AC-P3-003
- **Priority**：High
- **Test Steps**：
  1. `PATH=.venv/bin:$PATH python -m pytest tests/adapters/test_agent_adapter.py -v -k basic_execution`
- **Expected Results**：
  - 测试通过；返回 `SUCCESS`；输出包含任务文本片段

### TC-F-003：AgentAdapter 支持 prompt_template / system_prompt / skill 注入

- **Requirement**：AC-P3-003
- **Priority**：High
- **Test Steps**：
  1. `PATH=.venv/bin:$PATH python -m pytest tests/adapters/test_agent_adapter.py -v -k "prompt_template or system_prompt_as_initial_history or skill_injection or inject_to_skill"`
- **Expected Results**：
  - prompt_template 的 format 生效（输入字段正确替换）
  - system_prompt 转换为 `initial_history` 的 system 角色消息
  - Skill 内容被注入 task 文本（含 `SkillSpec.inject_to` 自动注入）

### TC-F-004：WorkflowAdapter 编排能力（Step/Loop/Parallel/Conditional/output_mappings）

- **Requirement**：AC-P3-004
- **Priority**：High
- **Test Steps**：
  1. `PATH=.venv/bin:$PATH python -m pytest tests/adapters/test_workflow_adapter.py -v`
- **Expected Results**：
  - 顺序步骤能读取前序 step 输出并映射到后续输入
  - LoopStep 使用 `runtime.loop_controller.run_loop` 并尊重 max_iterations
  - ParallelStep 支持 all_success/any_success 的 join 策略
  - ConditionalStep 能按条件选择分支
  - output_mappings 存在时按映射产出最终 output

### TC-F-005：SkillAdapter 内容加载（inline/file/uri）与 dispatch_rules

- **Requirement**：AC-P3-005
- **Priority**：High
- **Test Steps**：
  1. `PATH=.venv/bin:$PATH python -m pytest tests/adapters/test_skill_adapter.py -v`
- **Expected Results**：
  - inline/file 能返回内容
  - uri 默认失败（error 包含 allowlist/uri 相关提示）
  - dispatch_rules 触发时会调用目标能力并写入 `metadata.dispatched`

### TC-F-006：场景回归：WF-001D 人物塑造子流程

- **Requirement**：AC-P3-006
- **Priority**：High
- **Test Steps**：
  1. `PATH=.venv/bin:$PATH python -m pytest tests/scenarios/test_wf001d_character_creation.py -v`
- **Expected Results**：
  - Workflow 全流程 SUCCESS
  - 输出包含 `角色小传列表/角色关系图谱/视觉关键词列表` 且长度符合预期

### TC-F-007：场景回归：Workflow 嵌套 Workflow + 深度限制

- **Requirement**：AC-P3-006
- **Priority**：High
- **Test Steps**：
  1. `PATH=.venv/bin:$PATH python -m pytest tests/scenarios/test_nested_workflow.py -v`
- **Expected Results**：
  - “Workflow 调 Workflow” SUCCESS
  - 超过 `max_depth` 时返回 FAILED（recursion/depth 提示）

### TC-F-008：完整导入链验收（v0.4.0 ready）

- **Requirement**：AC-P3-008
- **Priority**：High
- **Test Steps**：
  1. 执行 Phase 3 spec 的“完整导入链验收” `python -c` 片段（见 `docs/specs/phases/phase3-adapters-scenarios.md` Test Plan）
- **Expected Results**：
  - 输出包含 `All imports OK — v0.4.0 ready`

---

## 2. Edge Case Tests

### TC-E-001：WorkflowAdapter LoopStep iterate_over 非 list

- **Requirement**：AC-P3-004
- **Priority**：Medium
- **Test Steps**：
  1. `PATH=.venv/bin:$PATH python -m pytest tests/adapters/test_workflow_adapter.py -v -k iterate_over_not_list`
- **Expected Results**：
  - 返回 FAILED 且错误提示包含 expected list

### TC-E-002：AgentAdapter prompt_template format 缺字段（KeyError 回退）

- **Requirement**：AC-P3-003
- **Priority**：Low
- **Test Steps**：
  1. `PATH=.venv/bin:$PATH python -m pytest tests/adapters/test_agent_adapter.py -v -k prompt_template_missing_key`
- **Expected Results**：
  - task 文本包含原模板与输入 JSON（不抛异常）

---

## 3. Error Handling Tests

### TC-ERR-001：WorkflowAdapter 不得 import agently/agent_sdk（静态检查）

- **Requirement**：AC-P3-002
- **Priority**：High
- **Test Steps**：
  1. `rg -n "\\b(from|import)\\s+agently\\b|\\b(from|import)\\s+agent_sdk\\b" src/agently_skills_runtime/adapters/workflow_adapter.py -S`
- **Expected Results**：
  - 无输出（未发现 import）

### TC-ERR-002：Workflow 步骤失败应立即 abort（不执行后续步骤）

- **Requirement**：AC-P3-004
- **Priority**：High
- **Test Steps**：
  1. `PATH=.venv/bin:$PATH python -m pytest tests/adapters/test_workflow_adapter.py -v -k step_failure_aborts_workflow`
- **Expected Results**：
  - Workflow 返回 FAILED
  - 后续步骤的 adapter 调用次数不增加（由测试断言保证）

---

## 4. State Transition Tests

### TC-ST-001：WF-001D 中循环步骤的 step_outputs 可被后续步骤消费

- **Requirement**：AC-P3-004, AC-P3-006
- **Priority**：High
- **Test Steps**：
  1. `PATH=.venv/bin:$PATH python -m pytest tests/scenarios/test_wf001d_character_creation.py -v`
- **Expected Results**：
  - `relations` 能读取 `design` 的循环输出列表并产出关系图谱

---

## 5. Coverage Matrix

| Requirement ID | Test Cases | Coverage Status |
|---|---|---|
| AC-P3-001 | TC-F-001 | ✓ Complete |
| AC-P3-002 | TC-ERR-001 | ✓ Complete |
| AC-P3-003 | TC-F-002, TC-F-003, TC-E-002 | ✓ Complete |
| AC-P3-004 | TC-F-004, TC-E-001, TC-ERR-002 | ✓ Complete |
| AC-P3-005 | TC-F-005 | ✓ Complete |
| AC-P3-006 | TC-F-006, TC-F-007, TC-ST-001 | ✓ Complete |
| AC-P3-007 | （见 `pyproject.toml` 版本变更） | ✓ Complete（规格层） |
| AC-P3-008 | TC-F-008 | ✓ Complete |

