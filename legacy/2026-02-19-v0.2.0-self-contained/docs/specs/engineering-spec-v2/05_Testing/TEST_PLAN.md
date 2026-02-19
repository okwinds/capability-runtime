# 测试计划（Test Plan, v2）

> 目标：定义离线回归命令与测试覆盖范围，作为“功能完成”的门禁。
>
> 真相源：`instructcontext/CODEX_PROMPT.md`（Step 5 测试清单）

---

## 1) 测试分层

### Unit / Offline Regression（必须）

特点：
- 不依赖外网
- 尽量不依赖真实上游（protocol/runtime 单测必须可独立运行）

覆盖范围（必须）：

- `tests/protocol/test_context.py`
  - `resolve_mapping()`：6 种前缀全覆盖（含字段深入）
  - `child()`：递归深度限制（超限抛 `RecursionLimitError`）
- `tests/protocol/test_capability.py`
  - `CapabilitySpec` 构造
  - `CapabilityResult` 字段存在与默认值
- `tests/runtime/test_registry.py`
  - register/get/get_or_raise/list_by_kind
  - validate_dependencies：缺失依赖检测（含 Parallel/Conditional 嵌套提取）
- `tests/runtime/test_loop.py`
  - 正常循环
  - max_iterations 超限
  - 单次迭代失败中止（partial 输出 + failed_at）
- `tests/runtime/test_guards.py`
  - LoopBreakerError 触发与行为
- `tests/runtime/test_engine.py`
  - mock adapters 的分发逻辑（Skill/Agent/Workflow 三类分发）

### Scenario / Regression Guards（强烈建议，v0.2.0 必须至少 1 条）

- `tests/scenarios/test_workflow_with_loop.py`
  - Workflow 编排 2 个 Agent + LoopStep（mock LLM）

### Integration（可选）

说明：
- adapter 涉及上游依赖与宿主对象（如 Agently agent 实例），可在开发机环境提供集成冒烟。
- 无环境时允许 skip，但必须有清晰 skip 条件与复现指引。

---

## 2) 离线回归命令（门禁）

全部回归：

```bash
pytest -q
```

按域回归（推荐实现阶段按 TDD 循环使用）：

```bash
pytest -q tests/protocol
pytest -q tests/runtime
pytest -q tests/scenarios
```

---

## 3) DoD（Definition of Done）

- 单测（离线回归）通过
- scenario 至少 1 条通过（workflow+loop）
- 关键公共导出可导入（import 回归用例或命令）
- `docs/worklog.md` 记录验证命令与结果（命令 + 输出摘要）

---

## 4) 假设（Assumptions）

- adapter 的真实上游执行细节不作为 v0.2.0 的硬门禁；但分发与协议一致性必须由 mock 测试锁定。

