# 架构（Architecture, v2）

> 目标：定义模块边界与依赖方向，确保“protocol/runtime 与上游解耦，adapters 集中承载上游变化”。

## 1) 模块拆分与职责

按 `instructcontext/1-true-CODEX_PROMPT.md`，目标包结构为：

- `agently_skills_runtime/protocol/`：能力协议（纯类型定义；零上游依赖）
- `agently_skills_runtime/runtime/`：能力运行时（注册表、执行引擎、循环控制、守卫；零上游依赖）
- `agently_skills_runtime/adapters/`：上游适配器（可依赖上游，但只使用 Public API）
- `agently_skills_runtime/reporting/`：执行报告聚合（v0.2.0 允许最小实现；不要求绑定业务）
- `agently_skills_runtime/errors.py`：框架错误定义（与 `ERROR_CATALOG.md` 对齐）

## 2) 依赖方向（必须遵守）

原则：

1. `protocol` 不依赖任何上游包
2. `runtime` 只依赖 `protocol`（不依赖 `adapters` 的上游实现细节）
3. `adapters` 允许依赖上游，但不得反向污染 `protocol/runtime`

依赖图（简化）：

```mermaid
flowchart LR
  subgraph Core[agently_skills_runtime core]
    Protocol[protocol/*\n(dataclass/Enum)]
    Runtime[runtime/*\n(engine/registry/loop/guards)]
    Errors[errors.py]
  end

  subgraph Adapters[adapters/*]
    SkillAdapter[skill_adapter.py]
    AgentAdapter[agent_adapter.py]
    WorkflowAdapter[workflow_adapter.py]
    LLMBackend[llm_backend.py]
  end

  subgraph Upstream[Upstream]
    Agently[agently]
    SDK[skills-runtime-sdk-python]
  end

  Protocol --> Runtime
  Errors --> Runtime
  Protocol --> Adapters
  Runtime --> Adapters
  LLMBackend --> Agently
  AgentAdapter --> SDK
  SkillAdapter --> SDK
  WorkflowAdapter --> SDK
```

## 3) 核心执行流（Runtime Dispatch）

统一入口：`CapabilityRuntime.run(capability_id, input, context_bag, run_id, max_depth)`

关键行为：

1. 构造/更新 `ExecutionContext`（run_id、max_depth、bag、call_chain）
2. 根据 registry 中 spec.kind 分发到对应 Adapter.execute()
3. Adapter 内部若需要嵌套执行，必须回到 runtime 的统一执行入口（保证深度守卫与 call_chain 一致）
4. 返回统一的 `CapabilityResult`

## 4) 上游边界（Protocol/Runtime 无上游依赖）

- `protocol/*` 内的类型禁止引用上游类型（包括但不限于 Agently 的 Agent/Requester 类型、SDK 的事件/工具类型）。
- `runtime/*` 的核心算法（registry、loop、guards）必须可在“无上游依赖”的环境下通过单测验证。
- `adapters/*` 是唯一允许出现上游 import 的目录；且不得 import 上游私有模块路径。

## 5) 假设（Assumptions）

- `reporting/*` 在 v0.2.0 可以以“最小可用”落地（例如以 JSON 可序列化 dict 承载事件聚合），不作为 protocol/runtime 的硬依赖。
