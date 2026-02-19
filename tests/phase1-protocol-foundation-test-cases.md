# Test Cases：Phase 1 — Protocol Foundation（系统/场景）

## Overview

- **Feature**：Protocol 层（纯类型定义）+ Bridge 入口重命名 + 包级导出面 + 统一错误导出
- **Requirements Source**：
  - Phase 1 指令（真相源）：`instructcontext/4-true-codex-phase1-protocol-foundation.md`
  - Phase 1 工程规格：`docs/specs/phases/phase1-protocol-foundation.md`
- **Last Updated**：2026-02-19

本文件是 Phase 1 的“手工/场景测试用例文档”，用于在实现阶段提供可操作的验收步骤与 Coverage Matrix。覆盖范围包含：

- Functional（主流程）
- Edge（边界条件）
- Error（错误处理）
- State Transition（与 `ExecutionContext` 相关的状态演进）

> 说明：本文件是测试规格（Test Spec）。实现落地后，关键用例应沉淀为 `tests/protocol/*` 的离线单测，并在 worklog 记录回归命令与结果。

---

## 1. Functional Tests

### TC-F-001：Capability 枚举值稳定（字符串值不漂移）
- **Requirement**：AC-P1-002
- **Priority**：High
- **Preconditions**：
  - 已按 Phase 1 完成 `protocol/capability.py` 实现
- **Test Steps**：
  1. 运行 `python -c "from agently_skills_runtime.protocol.capability import CapabilityKind; print([k.value for k in CapabilityKind])"`
  2. 手工比对输出
- **Expected Results**：
  - 输出必须包含且仅包含：`skill`、`agent`、`workflow`（顺序不强制，但值必须稳定）
- **Postconditions**：无

### TC-F-002：CapabilitySpec 默认值正确（不写也能用）
- **Requirement**：AC-P1-002
- **Priority**：High
- **Preconditions**：
  - 已实现 `CapabilitySpec`
- **Test Steps**：
  1. 运行：
     - `python -c "from agently_skills_runtime.protocol.capability import CapabilitySpec, CapabilityKind; s=CapabilitySpec(id='x', kind=CapabilityKind.SKILL, name='x'); print(s.description, s.version, s.tags, s.metadata)"`
- **Expected Results**：
  - `description==""`
  - `version=="0.1.0"`
  - `tags==[]`
  - `metadata=={}`

### TC-F-003：SkillSpec（file/inline）与 DispatchRule 结构可构造
- **Requirement**：AC-P1-002
- **Priority**：Medium
- **Preconditions**：
  - 已实现 `protocol/skill.py`
- **Test Steps**：
  1. 运行 `python -m pytest tests/protocol/test_skill.py -v`
- **Expected Results**：
  - 测试通过
  - 覆盖点至少包括：
    - `source_type="file"` 与 `"inline"` 的构造
    - `dispatch_rules` 默认空
    - `inject_to` 可存储多个 Agent ID

### TC-F-004：AgentSpec（最小/完整）与 AgentIOSchema 默认值
- **Requirement**：AC-P1-002
- **Priority**：Medium
- **Preconditions**：
  - 已实现 `protocol/agent.py`
- **Test Steps**：
  1. 运行 `python -m pytest tests/protocol/test_agent.py -v`
- **Expected Results**：
  - 测试通过
  - 覆盖点至少包括：
    - `skills/tools/collaborators/callable_workflows` 默认空列表
    - `llm_config/prompt_template/system_prompt` 默认 `None`
    - `AgentIOSchema.fields/required` 默认空

### TC-F-005：WorkflowSpec 及四类 Step 类型可构造
- **Requirement**：AC-P1-002
- **Priority**：Medium
- **Preconditions**：
  - 已实现 `protocol/workflow.py`
- **Test Steps**：
  1. 运行 `python -m pytest tests/protocol/test_workflow.py -v`
- **Expected Results**：
  - 测试通过
  - 覆盖点至少包括：
    - `Step`、`LoopStep`、`ParallelStep`、`ConditionalStep`
    - `InputMapping` 的 `source/target_field`

### TC-F-006：ExecutionContext.resolve_mapping 六类前缀行为一致
- **Requirement**：AC-P1-002
- **Priority**：High
- **Preconditions**：
  - 已实现 `protocol/context.py`
- **Test Steps**：
  1. 运行 `python -m pytest tests/protocol/test_context.py -v -k resolve_mapping`
- **Expected Results**：
  - 测试通过
  - 对“找不到”的情况返回 `None`（不抛异常）

### TC-F-007：errors.py 的错误导出面可用（含 RecursionLimitError re-export）
- **Requirement**：AC-P1-003
- **Priority**：High
- **Preconditions**：
  - 已实现 `src/agently_skills_runtime/errors.py`
- **Test Steps**：
  1. 运行：
     - `python -c "from agently_skills_runtime.errors import RecursionLimitError, CapabilityNotFoundError; print(RecursionLimitError.__name__, CapabilityNotFoundError.__name__)"`
- **Expected Results**：
  - 进程正常退出（导入成功）
  - 能打印出类名

### TC-F-008：包级导出面（Bridge + Protocol）可一次性导入
- **Requirement**：AC-P1-004
- **Priority**：High
- **Preconditions**：
  - 已按 Phase 1 更新 `src/agently_skills_runtime/__init__.py`
  - `runtime.py` 已重命名为 `bridge.py`
- **Test Steps**：
  1. 执行 Phase 1 指令中“验证导入”的 `python -c` 片段（见 spec 的 Test Plan 5.3）
- **Expected Results**：
  - 输出包含 `Protocol imports OK` 与 `Bridge imports OK`

### TC-F-009：桥接入口重命名生效（为 runtime/ 让路）
- **Requirement**：AC-P1-001
- **Priority**：High
- **Preconditions**：
  - 已执行 `runtime.py` → `bridge.py` 重命名
- **Test Steps**：
  1. 检查文件存在性：
     - `test -f src/agently_skills_runtime/bridge.py && echo OK`
  2. （可选）确认不存在 `src/agently_skills_runtime/runtime/` 的命名冲突
- **Expected Results**：
  - `bridge.py` 存在

---

## 2. Edge Case Tests

### TC-E-001：resolve_mapping 未知前缀/空字符串返回 None
- **Requirement**：AC-P1-002
- **Priority**：Medium
- **Preconditions**：
  - 已实现 `ExecutionContext.resolve_mapping`
- **Test Steps**：
  1. 运行 `python -m pytest tests/protocol/test_context.py -v -k unknown_prefix`
- **Expected Results**：
  - 返回 `None`，测试通过

### TC-E-002：previous 前缀在 step_outputs 为空时返回 None
- **Requirement**：AC-P1-002
- **Priority**：Medium
- **Preconditions**：同上
- **Test Steps**：
  1. 运行 `python -m pytest tests/protocol/test_context.py -v -k previous_no_outputs`
- **Expected Results**：
  - 返回 `None`，测试通过

### TC-E-003：item 前缀在未设置 __current_item__ 时返回 None
- **Requirement**：AC-P1-002
- **Priority**：Low
- **Preconditions**：同上
- **Test Steps**：
  1. 运行 `python -m pytest tests/protocol/test_context.py -v -k item_no_current_item`
- **Expected Results**：
  - 返回 `None`，测试通过

### TC-E-004：CapabilityRef 不指定 kind 也可构造（kind=None）
- **Requirement**：AC-P1-002
- **Priority**：Low
- **Preconditions**：
  - 已实现 `CapabilityRef`
- **Test Steps**：
  1. 运行 `python -m pytest tests/protocol/test_capability.py -v -k ref_no_kind`
- **Expected Results**：
  - `kind is None`，测试通过

---

## 3. Error Handling Tests

### TC-ERR-001：child() 超过 max_depth 必须抛 RecursionLimitError（含调用链）
- **Requirement**：AC-P1-002, AC-P1-003
- **Priority**：High
- **Preconditions**：
  - 已实现 `ExecutionContext.child` 与 `RecursionLimitError`
- **Test Steps**：
  1. 运行 `python -m pytest tests/protocol/test_context.py -v -k exceeds_max_depth`
- **Expected Results**：
  - 抛出 `RecursionLimitError`
  - 错误信息包含 `exceeds max`（或等价）与 `Call chain`（或等价调用链信息）

### TC-ERR-002：Protocol 层不得 import agently/agent_sdk（静态检查）
- **Requirement**：AC-P1-002
- **Priority**：High
- **Preconditions**：
  - Protocol 代码已生成
- **Test Steps**：
  1. 执行：
     - `grep -r "import agently" src/agently_skills_runtime/protocol/ && echo FAIL || echo OK`
     - `grep -r "import agent_sdk" src/agently_skills_runtime/protocol/ && echo FAIL || echo OK`
- **Expected Results**：
  - 两条命令都输出 `OK`（未发现 import）

---

## 4. State Transition Tests

### TC-ST-001：child() depth 递增，且 bag 为浅拷贝（子改不影响父）
- **Requirement**：AC-P1-002
- **Priority**：High
- **Preconditions**：
  - 已实现 `ExecutionContext.child`
- **Test Steps**：
  1. 运行 `python -m pytest tests/protocol/test_context.py -v -k child_increments_depth`
  2. 运行 `python -m pytest tests/protocol/test_context.py -v -k inherits_bag_as_copy`
- **Expected Results**：
  - depth 递增
  - 子 `bag` 修改不会影响父 `bag`

### TC-ST-002：child() 的 step_outputs 必须清空（隔离步骤输出空间）
- **Requirement**：AC-P1-002
- **Priority**：Medium
- **Preconditions**：同上
- **Test Steps**：
  1. 运行 `python -m pytest tests/protocol/test_context.py -v -k empty_step_outputs`
- **Expected Results**：
  - 子 context 的 `step_outputs == {}`

---

## 5. Test Coverage Matrix

| Requirement ID | Test Cases | Coverage Status |
|---|---|---|
| AC-P1-001 | TC-F-009 | ✓ Complete（规格层） |
| AC-P1-002 | TC-F-001, TC-F-002, TC-F-003, TC-F-004, TC-F-005, TC-F-006, TC-E-001, TC-E-002, TC-E-003, TC-E-004, TC-ERR-001, TC-ERR-002, TC-ST-001, TC-ST-002 | ✓ Complete（规格层） |
| AC-P1-003 | TC-F-007, TC-ERR-001 | ✓ Complete（规格层） |
| AC-P1-004 | TC-F-008 | ✓ Complete（规格层） |
| AC-P1-005 | TC-F-003, TC-F-004, TC-F-005, TC-F-006 | ⚠ Partial（需结合全量 pytest -q 验收） |
| AC-P1-006 | TC-F-003, TC-F-004, TC-F-005, TC-F-006（单测） + `python -m pytest -q`（回归） | ⚠ Needs execution evidence |
| AC-P1-007 | （发布策略项）以版本号检查为准 | ⚠ Out of scope（本文件不替代发布流程） |

## Notes

- 若实现阶段选择保留 `runtime.py` shim（兼容模块路径），请在 Coverage Matrix 中补充对应用例，并在 spec 中明确 deprecated 周期与验收口径。

