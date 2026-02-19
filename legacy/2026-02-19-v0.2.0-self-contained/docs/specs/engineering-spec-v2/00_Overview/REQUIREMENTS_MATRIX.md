# 需求矩阵（Requirements Matrix, v2）

> 目的：把 PRD 与 `instructcontext/1-true-CODEX_PROMPT.md` 的要求拆成可实现、可测试、可追溯的条目。
>
> Owner 口径：
> - **Protocol（This Repo）**：协议层类型定义（不依赖上游）
> - **Runtime（This Repo）**：执行引擎/注册表/循环控制/守卫
> - **Adapters（This Repo）**：上游适配器（允许依赖上游）
> - **Upstream**：上游能力（本仓不实现，仅适配与集成）

## 1) Functional Requirements（FR）

| ID | Requirement | Owner | Priority | Source |
|---|-------------|-------|----------|--------|
| FR-001 | 定义统一能力协议：CapabilityKind/Spec/Ref/Result/Status | Protocol | P0 | CODEX_PROMPT §protocol/capability.py |
| FR-002 | 定义 SkillSpec 与 SkillDispatchRule（含 inject_to、dispatch_rules） | Protocol | P0 | CODEX_PROMPT §protocol/skill.py |
| FR-003 | 定义 AgentSpec 与 AgentIOSchema（含 skills/tools/collaborators/workflows） | Protocol | P0 | CODEX_PROMPT §protocol/agent.py |
| FR-004 | 定义 WorkflowSpec 与 Step/Loop/Parallel/Conditional/InputMapping | Protocol | P0 | CODEX_PROMPT §protocol/workflow.py |
| FR-005 | ExecutionContext：child() 深度限制 + resolve_mapping 6 前缀 | Protocol | P0 | CODEX_PROMPT §protocol/context.py |
| FR-006 | CapabilityRegistry：register/get/get_or_raise/list_by_kind/validate_dependencies | Runtime | P0 | CODEX_PROMPT §runtime/registry.py |
| FR-007 | CapabilityRuntime：register/validate/run + 分发到各 Adapter | Runtime | P0 | CODEX_PROMPT §runtime/engine.py |
| FR-008 | LoopController：双重迭代上限 + 失败中止 + partial 输出 | Runtime | P0 | CODEX_PROMPT §runtime/loop.py |
| FR-009 | ExecutionGuards：全局 loop iteration 熔断（LoopBreakerError） | Runtime | P0 | CODEX_PROMPT §runtime/guards.py |
| FR-010 | LLM backend 迁移：agently_backend.py → llm_backend.py（功能不变） | Adapters | P0 | CODEX_PROMPT §adapters/llm_backend.py |
| FR-011 | SkillAdapter：加载内容 + dispatch_rules 调度（Phase 1 最小条件评估） | Adapters | P0 | CODEX_PROMPT §adapters/skill_adapter.py |
| FR-012 | AgentAdapter：注入 skills 内容，桥接 LLM backend，收集执行报告 | Adapters | P0 | CODEX_PROMPT §adapters/agent_adapter.py |
| FR-013 | WorkflowAdapter：执行 steps，写入 step_outputs，失败短路，输出映射 | Adapters | P0 | CODEX_PROMPT §adapters/workflow_adapter.py |
| FR-014 | 公共导出（__init__）：对外 API 列表必须稳定可用 | Runtime | P0 | CODEX_PROMPT §__init__.py |

## 2) Non-Functional Requirements（NFR）

| ID | Requirement | Target | Priority | Evidence |
|---|-------------|--------|----------|----------|
| NFR-001 | 可复刻 | 仅凭文档 + 依赖即可安装并跑离线回归 | P0 | `00_Overview/TECH_STACK.md` + `05_Testing/TEST_PLAN.md` |
| NFR-002 | 可回归 | protocol/runtime/loop 有单测，workflow 有 scenario 护栏 | P0 | `05_Testing/*` |
| NFR-003 | 上游零侵入 | 不 fork、不侵入上游；adapters 只用 Public API | P0 | `02_Technical_Design/ARCHITECTURE.md` |
| NFR-004 | 通用性 | 不绑业务，不强制 domain JSON 输出 | P0 | PRD Non-goals + 设计边界说明 |
| NFR-005 | 异常可诊断 | 错误类型与抛出场景可追踪，测试覆盖关键边界 | P0 | `02_Technical_Design/ERROR_CATALOG.md` + tests |
