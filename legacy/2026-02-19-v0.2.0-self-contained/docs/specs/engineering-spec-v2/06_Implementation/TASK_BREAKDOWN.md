# 任务拆解（Task Breakdown, v2）

> 目标：把 `instructcontext/CODEX_PROMPT.md` 的 Step 1~6 拆成可按 TDD 循环执行的任务清单。
>
> 约束：严格 Doc/Spec First + TDD（RED → GREEN → REFACTOR），并在 `docs/worklog.md` 记录命令与结果。

---

## Step 1：创建 protocol/（纯类型定义）

交付物：
- `protocol/capability.py`
- `protocol/skill.py`
- `protocol/agent.py`
- `protocol/workflow.py`
- `protocol/context.py`

TDD 建议（先测后写）：
- `tests/protocol/test_capability.py`
- `tests/protocol/test_context.py`

验收点：
- `ExecutionContext.child()` 深度超限抛 `RecursionLimitError`
- `ExecutionContext.resolve_mapping()` 覆盖 6 前缀

---

## Step 2：创建 runtime/

交付物：
- `runtime/registry.py`
- `runtime/guards.py`
- `runtime/loop.py`
- `runtime/engine.py`

TDD 建议：
- `tests/runtime/test_registry.py`
- `tests/runtime/test_guards.py`
- `tests/runtime/test_loop.py`
- `tests/runtime/test_engine.py`（mock adapters）

验收点：
- registry 依赖校验能检测缺失能力引用
- loop 双重迭代限制生效
- runtime 分发逻辑正确

---

## Step 3：创建 adapters/

交付物：
- `adapters/llm_backend.py`（从现有迁移，功能不变）
- `adapters/skill_adapter.py`
- `adapters/agent_adapter.py`
- `adapters/workflow_adapter.py`

TDD 建议：
- adapter 的真实上游集成可选（优先用 mock 锁定分发与协议形态）

验收点：
- runtime 能调用 adapter 并返回 `CapabilityResult`

---

## Step 4：更新入口与错误定义

交付物：
- 重写 `__init__.py`（对外导出清单见 `02_Technical_Design/PUBLIC_API.md`）
- 更新 `pyproject.toml`（版本目标 0.2.0；依赖与 pytest 配置保持可回归）
- 创建 `errors.py`（与 `02_Technical_Design/ERROR_CATALOG.md` 对齐）

验收点：
- 导入验收：`python -c "from agently_skills_runtime import CapabilityRuntime, SkillSpec, AgentSpec, WorkflowSpec"`

---

## Step 5：编写测试（门禁）

按 `05_Testing/TEST_PLAN.md` 与 `05_Testing/TRACEABILITY.md` 落地测试文件，确保离线回归可跑。

验收点：
- `pytest -q tests/protocol/` 全部通过
- `pytest -q tests/runtime/` 全部通过
- scenario 至少 1 条通过（workflow + loop）

---

## Step 6：清理与归档（legacy）

交付物：
- 旧 `runtime.py/types.py` 等按 `06_Implementation/MIGRATION.md` 归档到 `legacy/`
- README 更新（以新主线为入口）

验收点：
- 新主线入口清晰，旧资产可追溯但不干扰
- `DOCS_INDEX.md`、worklog、任务总结同步更新

