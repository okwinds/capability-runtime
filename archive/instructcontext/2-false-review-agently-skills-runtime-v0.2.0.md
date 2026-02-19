# Review: `agently-skills-runtime` v0.2.0 — instructcontext 对标审视

> 审视日期：2026-02-19
> 真相源：`instructcontext/1-true-CODEX_PROMPT.md` + `instructcontext/1-true-agently-skills-runtime-spec-v1.md`

---

## 一、当前完成度总览

### CODEX_PROMPT Step 1~6 执行情况

| Step | 交付物 | 状态 | 备注 |
|------|--------|------|------|
| Step 1: Protocol | capability/skill/agent/workflow/context.py | ✅ 完成 | 5 文件齐全，frozen dataclass，不依赖上游 |
| Step 2: Runtime | registry/guards/loop/engine.py | ✅ 完成 | 注册、校验、守卫、分发齐全 |
| Step 3: Adapters | skill/agent/workflow_adapter.py | ⚠️ 骨架完成 | 可测试，但无生产 runner |
| Step 3: Adapters | llm_backend.py | ❌ 未迁移 | 从旧 agently_backend.py 迁移未执行 |
| Step 4: 入口 | \_\_init\_\_.py / pyproject.toml / errors.py | ✅ 完成 | 导出清单完整 |
| Step 5: 测试 | protocol/runtime/scenario tests | ✅ 基本完成 | 覆盖核心路径 |
| Step 6: 清理 | legacy 归档 / README 更新 | ✅ 完成 | 旧代码归档到 legacy/ |

### 验收口径对标

| 验收条件 | 状态 |
|----------|------|
| `pip install -e .` 成功 | ✅ |
| import CapabilityRuntime/SkillSpec/AgentSpec/WorkflowSpec | ✅ |
| `pytest tests/protocol/` 全部通过 | ✅ |
| `pytest tests/runtime/` 全部通过 | ✅ |
| Scenario: Workflow + 2 Agent + LoopStep (mock) | ✅ |
| registry.validate_dependencies() 检测缺失 | ✅ |
| context.child() 超限抛 RecursionLimitError | ✅ |
| context.resolve_mapping() 覆盖 6 前缀 | ✅ |

**结论：按 CODEX_PROMPT 的最低验收门禁，v0.2.0 已通过。**

---

## 二、按 instructcontext 指令主旨，缺什么？

### 🔴 关键缺失（阻塞"快速落地"）

#### 1. `adapters/llm_backend.py` — LLM 传输桥接未迁移

CODEX_PROMPT 明确要求"从现有 `adapters/agently_backend.py` 直接迁移，保持所有功能不变"。这是整个框架从"协议空转"走向"真实执行"的唯一通路。

**现状**：旧代码在 `legacy/2026-02-18-bridge-only-mainline/` 里有完整的 `AgentlyChatBackend` + `AgentlyRequester` + `build_openai_compatible_requester_factory`，但从未被迁移到新主线的 `src/agently_skills_runtime/adapters/llm_backend.py`。

**影响**：AgentAdapter 当前只能用注入的 mock runner 跑测试，无法连接真实 LLM。框架"能组合但不能执行"。

#### 2. AgentAdapter 缺少默认生产 Runner

当前 AgentAdapter 通过 `AgentRunner` Protocol 注入 runner，测试中用 lambda mock。但没有提供一个默认的 `AgentlyRunner`（调用 llm_backend → Agently → SDK Agent），意味着业务层必须自己写 runner 才能让 Agent 跑起来。

**应有的形态**：提供 `DefaultAgentRunner`（可选依赖上游），在 `pip install agently-skills-runtime[full]` 时启用。

#### 3. SkillAdapter 的 `dispatch_rules` 条件评估仅支持"检查 bag key 存在"

CODEX_PROMPT 说"Phase 1 检查 bag key"。当前 `_evaluate_condition` 仅做 `key in context.bag`。对于业务场景（如"当 genre == 'fantasy' 时调度 fantasy-guide skill"），这远远不够。

**建议**：至少支持简单的等值比较表达式（`context.genre == "fantasy"`），或定义一个 condition evaluator 接口供业务层注入。

---

### 🟡 重要缺失（影响可靠性和可用性）

#### 4. WorkflowAdapter 的 ParallelStep / ConditionalStep 无测试覆盖

协议层定义了 `ParallelStep`（并行执行多分支）和 `ConditionalStep`（条件路由），WorkflowAdapter 的代码也实现了对应的 `_execute_step` 分支。但测试中 **只覆盖了 Step + LoopStep**，ParallelStep 和 ConditionalStep 没有任何测试。

这两个是 Workflow 编排的核心能力，没有测试护栏意味着重构时可能悄悄 break。

#### 5. Reporting 未接入 Adapter 执行流

`ReportBuilder` 已实现（emit/set_meta/build），但 **没有任何 Adapter 在执行过程中调用 ReportBuilder**。`CapabilityResult.report` 字段始终为 `None`。

**应有的形态**：
- engine.run() 创建 ReportBuilder
- 传递给每个 Adapter 的 execute()
- Adapter 在关键节点 emit 事件（step.started / step.completed / loop.iteration 等）
- 最终 build() 挂到 CapabilityResult.report

#### 6. `adapters/upstream.py` 是最小形态

当前只做 `importlib.util.find_spec()` 检查模块是否存在。不校验版本号（Agently 4.0.7 / SDK 0.1.1 的 pin）。

---

### 🟢 次要缺失（优化项，不阻塞落地）

#### 7. 无 YAML 声明式能力注册

当前只能 Python 代码注册能力（programmatic）。spec-v1 里暗示了"配置路径"（`sdk_config_paths`），但没有 YAML → Spec 的加载器。对于业务层快速声明多个 Skill/Agent/Workflow，纯代码注册较重。

#### 8. config.py 的 `skill_uri_allowlist` 未出现在 CODEX_PROMPT

RuntimeConfig 多了 `skill_uri_allowlist` 字段，这在 CODEX_PROMPT 中没有定义。这是实现层自加的安全特性（好的），但应该在文档中说明。

#### 9. 测试目录结构与 CODEX_PROMPT Step 5 的规定不完全一致

CODEX_PROMPT 要求：
- `tests/protocol/test_capability.py` — 存在
- `tests/runtime/test_registry.py` — 存在
- `tests/runtime/test_loop.py` — 存在
- `tests/runtime/test_guards.py` — 存在
- `tests/runtime/test_engine.py` — 存在
- `tests/scenarios/test_workflow_with_loop.py` — 存在
- `tests/adapters/` — 存在（额外加分）

但 `tests/protocol/test_workflow.py` 不存在（WorkflowSpec 构造的单测）。

---

## 三、下一步应该做什么？（优先级排序）

### P0：让框架能"真实执行"（1~2 天）

1. **迁移 llm_backend.py**：从 legacy 复制 AgentlyChatBackend + requester 到新主线
2. **实现 DefaultAgentRunner**：用 llm_backend 桥接，作为 AgentAdapter 的可选默认 runner
3. **补齐 upstream.py 版本 pin 校验**：至少 warn 级别报告版本不匹配

### P1：补齐测试护栏（1 天）

4. **ParallelStep scenario test**：并行执行 2 个 Agent，验证 join_strategy
5. **ConditionalStep scenario test**：按条件路由到不同分支
6. **SkillAdapter dispatch_rules test**：condition 匹配时委托目标能力
7. **SkillAdapter file/uri 加载 test**：不同 source_type 的加载路径

### P2：接入 Reporting + 增强条件评估（2~3 天）

8. **ReportBuilder 接入执行流**：engine/adapter 层 emit 事件
9. **增强 condition evaluator**：至少支持简单等值比较
10. **YAML 能力注册加载器**：从 YAML 文件批量注册 Spec

---

## 四、总体评估

**框架的"骨架"是扎实的。** Protocol 层设计干净、不依赖上游；Runtime 引擎的注册/校验/分发/循环控制逻辑完整；Adapter 的依赖注入设计使得测试非常干净。这些都是好的工程实践。

**但框架还不能"用起来"。** 从"协议空转"到"真实跑通一个 Agent"，缺的是 llm_backend.py 的迁移和 DefaultAgentRunner。这是最关键的一步——没有它，业务层看到的是一个"注册了能力声明但按下 run 什么也不发生"的框架。

**建议执行顺序**：先把 P0 的三件事做完（llm_backend 迁移 + DefaultAgentRunner + upstream pin），再补 P1 的测试护栏。P2 可以在首个业务场景跑通后再推进。
