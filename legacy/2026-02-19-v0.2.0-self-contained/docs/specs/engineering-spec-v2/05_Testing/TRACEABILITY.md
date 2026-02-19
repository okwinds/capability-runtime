# 追溯表（Traceability, v2）

> 目的：将需求（REQ/FR/NFR）映射到具体测试文件，确保“每条关键需求都有回归护栏”。
>
> 说明：本表在“文档阶段”先给出**可执行的落地计划**（文件路径与断言点），实现阶段必须创建对应测试文件并在任务总结中记录结果。

---

## 1) REQ → TEST 映射

| Requirement ID | Test File（计划） | 覆盖点（断言摘要） |
|---|---|---|
| FR-001 | `tests/protocol/test_capability.py` | CapabilityKind/Spec/Ref/Result/Status 字段与默认值 |
| FR-002 | `tests/protocol/test_context.py` | resolve_mapping（context/previous/step/literal/item）、child 深度限制 |
| FR-003 | `tests/runtime/test_registry.py` | registry 行为 + validate_dependencies 缺失依赖检测 |
| FR-004 | `tests/runtime/test_engine.py` | runtime 分发到 Skill/Agent/Workflow adapter |
| FR-005 | `tests/scenarios/test_workflow_with_loop.py` | workflow + loop 组合场景（mock LLM） |
| FR-008 | `tests/runtime/test_loop.py` | loop 双重上限、失败中止与 partial 输出 |
| FR-009 | `tests/runtime/test_guards.py` | LoopBreakerError 熔断 |
| FR-014 | `tests/runtime/test_engine.py` | 对外导入回归（或单独新增 import 测试） |
| NFR-001 | `docs/specs/engineering-spec-v2/00_Overview/TECH_STACK.md`（文档） | 可复刻命令在 worklog/summary 中有证据 |
| NFR-002 | `pytest -q`（流程门禁） | 离线回归稳定可跑 |
| NFR-003 | `tests/runtime/test_engine.py`（mock） + adapter 集成可选 | protocol/runtime 无上游依赖（可通过 import/运行证明） |

---

## 2) 执行阶段更新要求

- 实现阶段必须：
  - 创建上述测试文件；
  - 将本表中的“计划”更新为“已落地”，并在任务总结中记录测试命令与结果；
  - 若文件名或断言点调整，必须同步更新本表（避免断链）。
