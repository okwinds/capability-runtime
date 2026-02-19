# Test Cases：Skill-first Bridge × Host × RAG（系统级）

## Overview

- **Feature**：Skill-first Bridge（Agently TriggerFlow 编排 + 单智能体管理（Host）+ RAG（非侵入）+ Schema Gate（可选））
- **Requirements Source**：
  - PRD Addendum：`docs/prd/agently-skills-runtime-skill-first-bridge-host-rag.addendum.prd.md`
  - 需求矩阵：`docs/specs/engineering-spec/00_Overview/REQUIREMENTS_MATRIX.md`
  - Public API：`docs/specs/engineering-spec/02_Technical_Design/PUBLIC_API.md`
  - NodeReport 契约：`docs/specs/engineering-spec/02_Technical_Design/CONTRACTS.md`
- **Last Updated**：2026-02-16

本文件是“系统级测试用例文档”，用于覆盖：

- Functional（主流程）
- Edge（边界条件）
- Error（错误处理）
- State Transition（状态机）

> 说明：此处是测试规格（Test Spec）。实现阶段应把关键用例落地为离线单测/场景回归，并在 `TRACEABILITY.md` 中追溯。

---

## 1. Functional Tests

### TC-F-001：Extension Points（hooks）被调用并可观测
- **Requirement**：FR-009
- **Priority**：High
- **Preconditions**：
  - Host 注入一组 hooks（至少包含 `before_run`、`before_return_result`）
  - hooks 仅记录“被调用次数”与耗时
- **Test Steps**：
  1. Host 发起一次 turn 运行
  2. 运行完成后读取 `NodeReport.meta`
- **Expected Results**：
  - `NodeReport.meta.extension_trace[]` 存在并包含对应 hook 名称
  - 不包含 secrets/敏感内容
- **Postconditions**：无

### TC-F-002：单 turn 输出 NodeResult（三件套）
- **Requirement**：FR-010
- **Priority**：High
- **Preconditions**：
  - 具备一个可运行的 bridge runtime
- **Test Steps**：
  1. 发起 `run(task=...)`
  2. 获取返回值
- **Expected Results**：
  - 返回 `final_output`、`node_report`、`events_path`（允许为 null，但语义明确）
  - `node_report.schema=agently-skills-runtime.node_report.v2`

### TC-F-003：`initial_history` 注入可用于会话恢复（不记录内容）
- **Requirement**：FR-011
- **Priority**：High
- **Preconditions**：
  - Host 具备会话历史（至少 2 条消息）
- **Test Steps**：
  1. Host 带 `initial_history` 发起 turn
  2. 读取 `NodeReport.meta`
- **Expected Results**：
  - `NodeReport.meta.initial_history_injected=true`
  - NodeReport/WAL 中不出现历史消息原文（仅摘要/标志位）

### TC-F-004：RAG pre-run 注入（默认最小披露证据链）
- **Requirement**：FR-012, NFR-008, NFR-009
- **Priority**：High
- **Preconditions**：
  - Host 提供 RagProvider（可为 in-memory）
  - RAG 采用 pre-run 注入模式
- **Test Steps**：
  1. 发起 turn，触发一次检索（query 由 Host 或策略生成）
  2. 读取 NodeReport.meta.rag
- **Expected Results**：
  - `NodeReport.meta.rag.mode=pre_run`
  - `queries[].query_sha256` 存在
  - `chunks[]` 仅包含 doc_id/source/score/hash/len 等元信息

### TC-F-005：RAG tool 模式（tool evidence 可追溯）
- **Requirement**：FR-012, NFR-009
- **Priority**：Medium
- **Preconditions**：
  - Host 提供一个 `rag_retrieve` 工具（或等价）
- **Test Steps**：
  1. 模型在运行中触发 `rag_retrieve`
  2. 读取 NodeReport.tool_calls
- **Expected Results**：
  - tool_calls 中存在对应 `call_id` 与 `name=rag_retrieve`
  - tool 调用过程可在 WAL/NodeReport 中审计（不泄露 secrets）

### TC-F-006：Schema Gate（warn）不阻断但记录错误摘要
- **Requirement**：FR-013
- **Priority**：Medium
- **Preconditions**：
  - Host 注入 SchemaGate，mode=warn
  - 输出 payload 不符合 schema
- **Test Steps**：
  1. 发起 turn
  2. 读取 NodeReport.meta.schema_gate
- **Expected Results**：
  - `schema_gate.ok=false`
  - `NodeReport.status` 不变（仍 success 或其它）
  - errors 仅包含 path/kind/截断 message，不包含敏感值

### TC-F-007：Schema Gate（error）失败时 fail-closed（可编排分支）
- **Requirement**：FR-013
- **Priority**：High
- **Preconditions**：
  - Host 注入 SchemaGate，mode=error
  - 输出 payload 不符合 schema
- **Test Steps**：
  1. 发起 turn
  2. 读取 NodeReport.status/reason
- **Expected Results**：
  - `NodeReport.status=failed`
  - `NodeReport.reason=schema_validation_error`

---

## 2. Edge Case Tests

### TC-E-001：hooks 列表为空（扩展点 no-op）
- **Requirement**：FR-009, NFR-007
- **Priority**：Medium
- **Preconditions**：Host 不注入 hooks
- **Test Steps**：
  1. 发起 turn
  2. 读取 NodeReport.meta
- **Expected Results**：
  - 不报错
  - `extension_trace` 可缺失或为空（契约需明确二选一）

### TC-E-002：`initial_history` 为空列表
- **Requirement**：FR-011
- **Priority**：Low
- **Preconditions**：Host 提供 `initial_history=[]`
- **Test Steps**：
  1. 发起 turn
  2. 读取 NodeReport.meta
- **Expected Results**：
  - `initial_history_injected=true` 或明确为 false（实现需统一口径）
  - 无异常

### TC-E-003：RAG 返回 0 chunks
- **Requirement**：FR-012
- **Priority**：Medium
- **Preconditions**：RagProvider 返回空结果
- **Test Steps**：
  1. 发起 turn
  2. 读取 NodeReport.meta.rag
- **Expected Results**：
  - `chunks=[]` 且流程正常

---

## 3. Error Handling Tests

### TC-ERR-001：hook 抛异常不应泄露 secrets（默认 fail-open）
- **Requirement**：FR-009, NFR-008
- **Priority**：High
- **Preconditions**：
  - 注入一个 hook，在异常 message 中包含“模拟敏感值”
- **Test Steps**：
  1. 发起 turn
  2. 读取 NodeReport.meta.extension_errors
- **Expected Results**：
  - extension_errors 中不包含原始敏感值（需截断/脱敏）
  - 主流程仍可返回 NodeResult（除非 gate 配置要求 fail-closed）

### TC-ERR-002：RAG Provider 超时/失败
- **Requirement**：FR-012, NFR-009
- **Priority**：High
- **Preconditions**：RagProvider 抛超时异常
- **Test Steps**：
  1. 发起 turn
  2. 读取 NodeReport.status 与 meta.rag
- **Expected Results**：
  - 行为可配置：默认 fail-open（不阻断），但记录 `rag.error_kind=timeout`
  - 不应吞错；至少可观测到失败摘要

---

## 4. State Transition Tests

### TC-ST-001：RUNNING → NEEDS_APPROVAL（暂停交还 Host）
- **Requirement**：FR-010, NFR-009
- **Priority**：High
- **Preconditions**：
  - 模型触发一个 requires_approval 的工具调用
  - Host 不立即提供 approval_decided
- **Test Steps**：
  1. 发起 turn
  2. 读取 NodeReport.status
- **Expected Results**：
  - `NodeReport.status=needs_approval`
  - Host 可基于该状态暂停 TriggerFlow 节点并等待审批

### TC-ST-002：NEEDS_APPROVAL → RUNNING → SUCCESS（恢复）
- **Requirement**：FR-010
- **Priority**：High
- **Preconditions**：
  - TC-ST-001 已进入 NEEDS_APPROVAL
- **Test Steps**：
  1. Host 提交审批结果（approved）
  2. Host 再次发起继续运行（同 session）
- **Expected Results**：
  - 最终 `NodeReport.status=success`
  - tool_calls 中 approval_decision 与 call_id 关联正确

### TC-ST-003：RUNNING → INCOMPLETE（取消）
- **Requirement**：FR-010, NFR-009
- **Priority**：Medium
- **Preconditions**：cancel_checker 在运行中触发
- **Test Steps**：
  1. 发起 turn
  2. 触发取消
- **Expected Results**：
  - `NodeReport.status=incomplete`
  - `NodeReport.reason=cancelled`（或等价枚举）

---

## 5. Test Coverage Matrix

| Requirement ID | Test Cases | Coverage Status |
|---|---|---|
| FR-009 | TC-F-001, TC-E-001, TC-ERR-001 | ✓ Complete（规格层） |
| FR-010 | TC-F-002, TC-ST-001, TC-ST-002, TC-ST-003 | ✓ Complete（规格层） |
| FR-011 | TC-F-003, TC-E-002 | ✓ Complete（规格层） |
| FR-012 | TC-F-004, TC-F-005, TC-E-003, TC-ERR-002 | ✓ Complete（规格层） |
| FR-013 | TC-F-006, TC-F-007 | ✓ Complete（规格层） |
| NFR-006 | 通过所有用例的“职责边界断言”体现（Bridge 不落 DB/业务） | ⚠ Needs implementation guards |
| NFR-007 | TC-E-001（no-op）+ 兼容性测试（待实现） | ⚠ Partial |
| NFR-008 | TC-F-004, TC-ERR-001（脱敏） | ⚠ Partial |
| NFR-009 | TC-F-004, TC-F-005, TC-ST-001（可审计/可编排） | ⚠ Partial |

## Notes

- 本文件仅定义系统级测试规格；实现落地时需把关键用例拆为离线单测 + 参考应用场景回归，并更新 `docs/specs/engineering-spec/05_Testing/TRACEABILITY.md`。

