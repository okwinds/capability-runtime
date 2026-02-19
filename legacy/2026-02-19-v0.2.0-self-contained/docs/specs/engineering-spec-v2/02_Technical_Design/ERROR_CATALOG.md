# 错误目录（Error Catalog, v2）

> 目标：明确关键错误类型、抛出位置与处理策略，保证“失败可诊断、边界可回归”。

---

## 1) 协议层错误（protocol/）

### E-PROTO-001：RecursionLimitError

- 类型：`RecursionLimitError(Exception)`
- 抛出位置：`ExecutionContext.child()`
- 触发条件：`depth + 1 > max_depth`
- 处理建议：
  - runtime 捕获后返回 `CapabilityResult(status=FAILED, error=...)`
  - error 字符串必须包含深度与 `call_chain` 以便定位

### E-PROTO-002：ValueError（未知映射前缀）

- 类型：`ValueError`
- 抛出位置：`ExecutionContext.resolve_mapping()`
- 触发条件：expression 前缀不在 `context/previous/step/literal/item` 集合内
- 处理建议：视为调用方配置错误（workflow input_mappings 写错），应快速失败并返回 FAILED

---

## 2) 运行时错误（runtime/）

### E-RUNTIME-001：KeyError（能力不存在）

- 类型：`KeyError`
- 抛出位置：`CapabilityRegistry.get_or_raise()` 或 runtime 执行分发阶段
- 触发条件：能力 ID 未注册
- 处理建议：在 `CapabilityRuntime.validate()` 阶段尽可能提前暴露（依赖校验）

### E-RUNTIME-002：LoopBreakerError（全局循环熔断）

- 类型：`LoopBreakerError(Exception)`
- 抛出位置：`ExecutionGuards.record_loop_iteration()`
- 触发条件：全局 loop iteration 超过 `max_total_loop_iterations`
- 处理建议：
  - runtime 或 loop controller 捕获后返回 FAILED
  - error 需包含累计迭代次数与阈值

### E-RUNTIME-003：ValueError / TypeError（循环输入非集合或不可迭代）

- 类型：`ValueError` 或 `TypeError`
- 抛出位置：`LoopController.execute_loop()`（当 `iterate_over` 解析结果不符合预期）
- 触发条件：`iterate_over` 解析结果不是 list/tuple 等可迭代集合
- 处理建议：视为 workflow 配置错误，快速失败

---

## 3) Adapter 错误（adapters/）

> v0.2.0 允许 adapter 将上游异常转换为 `CapabilityResult(status=FAILED, error=...)`，避免把上游异常形态泄露到 protocol/runtime。

### E-ADAPTER-001：上游依赖不可用（ImportError / RuntimeError）

- 类型：`ImportError` 或 adapter 自定义 `RuntimeError`
- 触发条件：上游包缺失，或宿主未提供必要对象（例如 `RuntimeConfig.agently_agent` 为 None 且 agent adapter 需要）
- 处理建议：
  - 单测（protocol/runtime）不依赖 adapter
  - adapter 测试可通过 mock/skip 覆盖（见测试计划）

---

## 4) 统一错误呈现（CapabilityResult）

约束：

- 失败必须通过 `CapabilityResult.status == FAILED` 表示。
- `CapabilityResult.error` 必须是可诊断字符串：
  - 至少包含错误类型名与关键上下文（capability_id、step_id、call_chain 等）
  - 禁止仅写 “failed/exception happened” 之类不可定位信息

---

## 5) 假设（Assumptions）

- v0.2.0 已新增 `src/agently_skills_runtime/errors.py`（例如 `ConfigurationError`、`CapabilityNotFoundError`、`UpstreamVerificationError` 等）作为“可分类捕获”的错误类型集合。
- 当前主线仍以 `CapabilityResult(status=FAILED, error=...)` 作为统一失败呈现；后续若将上述错误类型纳入 runtime/adapters 的抛出/转换策略，需要同步更新本文件与测试追溯表。
