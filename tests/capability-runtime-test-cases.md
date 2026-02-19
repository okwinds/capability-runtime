# Test Cases：Capability-oriented Runtime（系统级骨架）

## Overview

- **Feature**：Capability-oriented Runtime（以“能力”为一等公民的运行时：注册/发现/执行/组合/可观测）
- **Requirements Source**：
  - PRD：`docs/prd/agently-skills-runtime-capability-runtime.prd.md`
  - 指令真相源（历史线）：`instructcontext/1-true-CODEX_PROMPT.md`
  - 归档工程规格（参考）：`legacy/2026-02-19-v0.2.0-self-contained/docs/specs/engineering-spec-v2/`
- **Last Updated**：2026-02-19

本文件用于补齐 `DOCS_INDEX.md` 中缺失的系统测试用例文档，并提供一个**可迁移、可复现、避免绑定具体业务**的测试骨架（Test Spec）。

> 说明：
> 1) 本仓当前主线为 Bridge/Glue（v0.3.x），Capability-oriented Runtime 属于历史实验线（v0.2.0）。  
> 2) 本文件不要求与当前实现 1:1 对齐；它的目的在于提供“能力运行时”通用测试维度与 Coverage Matrix，便于未来复用或回溯验收口径。  
> 3) 若后续继续演进该方向，建议把关键用例落地为离线单测/场景回归，并在 worklog 记录命令与结果证据。

---

## Requirements（用于追溯的最小集合）

- CR-REQ-001：能力可注册/可发现（Skill/Agent/Workflow）。
- CR-REQ-002：能力执行返回统一结果结构（status/output/error/report/artifacts 等）。
- CR-REQ-003：能力组合（Workflow steps / Agent collaborators）使用显式引用（CapabilityRef）且可校验。
- CR-REQ-004：上下文（context bag + step_outputs）可跨步骤传递并可追溯。
- CR-REQ-005：递归/嵌套调用有深度限制与明确错误（fail-fast，可观测）。
- CR-REQ-006：错误分层清晰（框架基础错误/找不到 Adapter/找不到 Capability 等）。
- CR-REQ-007：可观测与审计证据不泄露敏感信息（最小披露原则）。
- CR-REQ-008：离线回归可运行（无需外网/无需真实密钥）。

---

## 1. Functional Tests

### TC-F-001：能力注册与发现（最小闭环）
- **Requirement**：CR-REQ-001
- **Priority**：High
- **Preconditions**：
  - 存在一个能力注册表（Registry）或等价组件
  - 支持至少 3 类能力：Skill/Agent/Workflow
- **Test Steps**：
  1. 注册 1 个 Skill、1 个 Agent、1 个 Workflow（ID 互不冲突）
  2. 通过 ID 查询与枚举列表接口检索
- **Expected Results**：
  - 能通过 ID 精确取回对应能力
  - 列表/枚举结果可按 kind 过滤（或提供等价机制）

### TC-F-002：能力执行返回统一结果结构（成功路径）
- **Requirement**：CR-REQ-002
- **Priority**：High
- **Preconditions**：
  - 存在统一 `CapabilityResult`（或等价结构）
- **Test Steps**：
  1. 执行一个确定性能力（例如：输入字符串，返回大写字符串）
  2. 检查返回结构字段
- **Expected Results**：
  - `status=success`（或等价枚举）
  - `output` 存在且可被下游消费
  - `error is None`
  - `artifacts` 默认为空列表（如无产物）

### TC-F-003：Workflow 组合执行（Step + LoopStep）
- **Requirement**：CR-REQ-003, CR-REQ-004
- **Priority**：High
- **Preconditions**：
  - Workflow 支持 Step/LoopStep（或等价）
  - 上下文支持 `step_outputs` 与映射表达式（至少 step/context/item）
- **Test Steps**：
  1. 构造一个 workflow：
     - Step-1：产生一个列表 `items=[...]`
     - LoopStep：对 items 循环调用能力，收集结果
  2. 执行 workflow
- **Expected Results**：
  - `step_outputs` 能记录每个 step 的输出（或提供等价可追溯机制）
  - LoopStep 收集结果长度与 items 一致

### TC-F-004：ConditionalStep 分支选择（默认分支）
- **Requirement**：CR-REQ-003, CR-REQ-004
- **Priority**：Medium
- **Preconditions**：
  - 支持条件分支（ConditionalStep 或等价）
- **Test Steps**：
  1. 输入一个不在 branches 中的条件值
  2. 执行 workflow
- **Expected Results**：
  - 走 default 分支（或明确 fail-closed，二者选其一但需契约化）

### TC-F-005：错误类型可追溯（找不到能力）
- **Requirement**：CR-REQ-006
- **Priority**：High
- **Preconditions**：
  - 执行引擎在找不到能力时抛出结构化错误（异常或结果中的 error）
- **Test Steps**：
  1. 执行一个不存在的 capability_id
- **Expected Results**：
  - 抛 `CapabilityNotFoundError`（或等价错误类型），且错误信息不包含敏感值

---

## 2. Edge Case Tests

### TC-E-001：空 workflow（0 steps）处理策略明确
- **Requirement**：CR-REQ-002, CR-REQ-003
- **Priority**：Medium
- **Preconditions**：
  - 支持 workflow 定义
- **Test Steps**：
  1. 定义 steps=[]
  2. 执行 workflow
- **Expected Results**：
  - 要么 `success` 且 output 为空结构，要么 fail-closed 并给出明确错误；不得 silent 产生不一致状态

### TC-E-002：LoopStep iterate_over 解析为非 list（类型不匹配）
- **Requirement**：CR-REQ-004
- **Priority**：Medium
- **Preconditions**：同上
- **Test Steps**：
  1. 让 iterate_over 指向一个非 list 值（例如 dict/str/int）
  2. 执行 workflow
- **Expected Results**：
  - 明确失败并可观测（错误类型/错误码稳定），不得默默跳过

---

## 3. Error Handling Tests

### TC-ERR-001：递归深度超限（防止无限嵌套）
- **Requirement**：CR-REQ-005
- **Priority**：High
- **Preconditions**：
  - 存在 max_depth（或等价）限制
- **Test Steps**：
  1. 构造一个递归调用链（workflow→agent→workflow... 或直接 child context 链）
  2. 触发超过 max_depth
- **Expected Results**：
  - 抛出/返回明确错误（例如 `RecursionLimitError`）
  - 错误信息包含调用链摘要（便于排障），但不包含敏感 payload

### TC-ERR-002：Adapter 未注册（fail-fast）
- **Requirement**：CR-REQ-006
- **Priority**：High
- **Preconditions**：
  - 运行时存在 adapter registry（或等价）
- **Test Steps**：
  1. 请求一个未注册的 adapter 类型
- **Expected Results**：
  - 抛 `AdapterNotFoundError`（或等价）

---

## 4. State Transition Tests

### TC-ST-001：执行状态机枚举完整且一致
- **Requirement**：CR-REQ-002
- **Priority**：Medium
- **Preconditions**：
  - 能力执行返回 `status`
- **Test Steps**：
  1. 分别触发：成功、失败、取消（如支持）、运行中（如可观测）
  2. 读取 status 与可观测记录（report/events）
- **Expected Results**：
  - 状态值来自受控枚举集合（不出现“自由文本漂移”）
  - 失败时 error 字段存在且可追溯

---

## 5. Test Coverage Matrix

| Requirement ID | Test Cases | Coverage Status |
|---|---|---|
| CR-REQ-001 | TC-F-001 | ⚠ Partial（骨架覆盖，需实现落地） |
| CR-REQ-002 | TC-F-002, TC-ST-001, TC-E-001 | ⚠ Partial（骨架覆盖，需实现落地） |
| CR-REQ-003 | TC-F-003, TC-F-004 | ⚠ Partial（骨架覆盖，需实现落地） |
| CR-REQ-004 | TC-F-003, TC-F-004, TC-E-002 | ⚠ Partial（骨架覆盖，需实现落地） |
| CR-REQ-005 | TC-ERR-001 | ⚠ Partial（骨架覆盖，需实现落地） |
| CR-REQ-006 | TC-F-005, TC-ERR-002 | ⚠ Partial（骨架覆盖，需实现落地） |
| CR-REQ-007 | （贯穿所有用例的“最小披露断言”） | ⚠ Needs concrete observability contract |
| CR-REQ-008 | （离线回归命令与结果证据） | ⚠ Needs worklog evidence |

## Notes

- 本文件刻意不绑定特定业务名词/场景/供应商；若要写示例能力，建议使用“确定性、无外部依赖”的 toy 能力（例如字符串处理）来构造可离线回归的场景。
- 若未来把该方向重新拉回主线，请同步：
  - 把关键用例实现为离线单测/场景回归
  - 在 `docs/worklog.md` 记录回归命令与结果
  - 在 `DOCS_INDEX.md`/规格索引中更新引用路径（避免再次出现缺失引用）

