# 数据模型（Data Model, v2）

> 目标：把 v0.2.0 所需的 `dataclass/Enum/Exception` 字段清单写成“实现级”规格，便于直接照抄实现与单测断言。
>
> 真相源：`instructcontext/CODEX_PROMPT.md`

---

## 1) protocol/capability.py

### Enum：CapabilityKind

- `SKILL = "skill"`
- `AGENT = "agent"`
- `WORKFLOW = "workflow"`

### dataclass（frozen）：CapabilityRef

| 字段 | 类型 | 默认值 | 说明 |
|---|------|--------|------|
| `id` | `str` | 无 | 引用的能力 ID |
| `kind` | `Optional[CapabilityKind]` | `None` | 可选的类型提示（允许省略） |

### dataclass（frozen）：CapabilitySpec

| 字段 | 类型 | 默认值 | 说明 |
|---|------|--------|------|
| `id` | `str` | 无 | 能力唯一 ID（注册表主键） |
| `kind` | `CapabilityKind` | 无 | 能力类型 |
| `name` | `str` | 无 | 展示名 |
| `description` | `str` | `""` | 描述 |
| `version` | `str` | `"0.1.0"` | 能力版本（独立于包版本） |
| `tags` | `List[str]` | `[]` | 标签 |
| `metadata` | `Dict[str, Any]` | `{}` | 扩展元数据 |

### Enum：CapabilityStatus

- `PENDING / RUNNING / SUCCESS / FAILED / CANCELLED`

### dataclass：CapabilityResult

| 字段 | 类型 | 默认值 | 说明 |
|---|------|--------|------|
| `status` | `CapabilityStatus` | 无 | 执行状态 |
| `output` | `Any` | `None` | 输出（可为 dict/str/任意 JSON 可序列化结构） |
| `error` | `Optional[str]` | `None` | 错误信息（建议为可诊断字符串） |
| `report` | `Optional[Any]` | `None` | 执行报告（v0.2.0 允许最小实现为 dict） |
| `artifacts` | `List[str]` | `[]` | 产物路径/引用（可选） |

---

## 2) protocol/skill.py

### dataclass（frozen）：SkillDispatchRule

| 字段 | 类型 | 默认值 | 说明 |
|---|------|--------|------|
| `condition` | `str` | 无 | 触发条件（Phase 1：最小口径，可用 bag key 或简单表达式） |
| `target` | `CapabilityRef` | 无 | 目标能力引用 |
| `priority` | `int` | `0` | 优先级（大者优先或按实现约定；实现需在 spec/测试中锁定） |
| `metadata` | `Dict[str, Any]` | `{}` | 扩展元数据 |

### dataclass（frozen）：SkillSpec

| 字段 | 类型 | 默认值 | 说明 |
|---|------|--------|------|
| `base` | `CapabilitySpec` | 无 | 公共能力字段（kind 必须为 SKILL） |
| `source` | `str` | 无 | 内容源（文件路径/内联文本/URI） |
| `source_type` | `str` | `"file"` | `"file" \| "inline" \| "uri"` |
| `dispatch_rules` | `List[SkillDispatchRule]` | `[]` | 调度规则 |
| `inject_to` | `List[str]` | `[]` | 自动注入到哪些 Agent（按 AgentSpec.base.id 匹配） |

---

## 3) protocol/agent.py

### dataclass（frozen）：AgentIOSchema

| 字段 | 类型 | 默认值 | 说明 |
|---|------|--------|------|
| `fields` | `Dict[str, str]` | `{}` | 字段名 → 类型描述（轻量） |
| `required` | `List[str]` | `[]` | 必填字段列表 |

### dataclass（frozen）：AgentSpec

| 字段 | 类型 | 默认值 | 说明 |
|---|------|--------|------|
| `base` | `CapabilitySpec` | 无 | 公共能力字段（kind 必须为 AGENT） |
| `skills` | `List[str]` | `[]` | 装载的 Skill ID 列表 |
| `tools` | `List[str]` | `[]` | 工具 ID 列表（字符串占位；具体 tool 系统由 adapter/上游承载） |
| `collaborators` | `List[CapabilityRef]` | `[]` | 可协作的其他 Agent |
| `callable_workflows` | `List[CapabilityRef]` | `[]` | 可调用的 Workflow |
| `input_schema` | `Optional[AgentIOSchema]` | `None` | 输入 schema |
| `output_schema` | `Optional[AgentIOSchema]` | `None` | 输出 schema |
| `loop_compatible` | `bool` | `False` | 是否可被 LoopStep 调用 |
| `llm_config` | `Optional[Dict[str, Any]]` | `None` | LLM 覆盖配置（不设则继承全局） |

---

## 4) protocol/workflow.py

### dataclass（frozen）：InputMapping

| 字段 | 类型 | 默认值 | 说明 |
|---|------|--------|------|
| `source` | `str` | 无 | 映射表达式（见 ExecutionContext.resolve_mapping） |
| `target_field` | `str` | 无 | 写入目标 input 字段名 |

### dataclass（frozen）：Step

| 字段 | 类型 | 默认值 | 说明 |
|---|------|--------|------|
| `id` | `str` | 无 | 步骤 ID（用于 step_outputs key） |
| `capability` | `CapabilityRef` | 无 | 被执行的能力引用 |
| `input_mappings` | `List[InputMapping]` | `[]` | 输入映射 |

### dataclass（frozen）：LoopStep

| 字段 | 类型 | 默认值 | 说明 |
|---|------|--------|------|
| `id` | `str` | 无 | 步骤 ID |
| `capability` | `CapabilityRef` | 无 | 被循环执行的能力引用 |
| `iterate_over` | `str` | 无 | 映射表达式，解析得到集合 |
| `item_input_mappings` | `List[InputMapping]` | `[]` | item 级输入映射 |
| `max_iterations` | `int` | `100` | 步骤级最大迭代次数 |
| `collect_as` | `str` | `"results"` | 收集结果的字段名 |

### dataclass（frozen）：ParallelStep

| 字段 | 类型 | 默认值 | 说明 |
|---|------|--------|------|
| `id` | `str` | 无 | 步骤 ID |
| `branches` | `List[Union[Step, LoopStep]]` | `[]` | 并行分支（最小包含 Step/LoopStep） |
| `join_strategy` | `str` | `"all_success"` | `all_success \| any_success \| best_effort` |

### dataclass（frozen）：ConditionalStep

| 字段 | 类型 | 默认值 | 说明 |
|---|------|--------|------|
| `id` | `str` | 无 | 步骤 ID |
| `condition_source` | `str` | 无 | 映射表达式（解析得到条件值） |
| `branches` | `Dict[str, Union[Step, LoopStep]]` | `{}` | 条件值 → 分支 |
| `default` | `Optional[Union[Step, LoopStep]]` | `None` | 默认分支 |

### 类型别名：WorkflowStep

- `WorkflowStep = Union[Step, LoopStep, ParallelStep, ConditionalStep]`

### dataclass（frozen）：WorkflowSpec

| 字段 | 类型 | 默认值 | 说明 |
|---|------|--------|------|
| `base` | `CapabilitySpec` | 无 | 公共能力字段（kind 必须为 WORKFLOW） |
| `steps` | `List[WorkflowStep]` | `[]` | 步骤列表 |
| `context_schema` | `Optional[Dict[str, str]]` | `None` | 可选的 context schema（轻量） |
| `output_mappings` | `List[InputMapping]` | `[]` | 输出映射（构造最终输出） |

---

## 5) protocol/context.py

### Exception：RecursionLimitError

- 语义：嵌套深度超限（必须由 `ExecutionContext.child()` 抛出）。

### dataclass：ExecutionContext

| 字段 | 类型 | 默认值 | 说明 |
|---|------|--------|------|
| `run_id` | `str` | 无 | 本次 run 标识 |
| `parent_context` | `Optional[ExecutionContext]` | `None` | 父上下文 |
| `depth` | `int` | `0` | 当前深度 |
| `max_depth` | `int` | `10` | 最大深度（全局默认可由 RuntimeConfig 提供） |
| `bag` | `Dict[str, Any]` | `{}` | 共享上下文 bag |
| `step_outputs` | `Dict[str, Any]` | `{}` | workflow 步骤输出缓存 |
| `call_chain` | `List[str]` | `[]` | 调用链（能力 ID 列表） |

必备方法（实现级）：

- `child(capability_id: str) -> ExecutionContext`
  - 行为：depth+1、bag 浅拷贝、step_outputs 清空、call_chain 追加
  - 超限：`depth + 1 > max_depth` 必须抛 `RecursionLimitError`，错误信息包含深度与调用链

- `resolve_mapping(expression: str) -> Any`
  - 行为：支持 `context/previous/step/literal/item` 五类定位（含 `item` 的字段深入）
  - 未知前缀：必须抛 `ValueError`

---

## 6) runtime/config（RuntimeConfig）

> 注：RuntimeConfig 属于 runtime/engine.py 的数据结构，在 `04_Operations/CONFIGURATION.md` 详细定义。

字段（以 CODEX_PROMPT 的注释为准）：

- `workspace_root: str = "."`
- `sdk_config_paths: List[str] = []`
- `agently_agent: Any = None`
- `preflight_mode: str = "error"`（`error | warn | off`）
- `max_loop_iterations: int = 200`
- `max_depth: int = 10`
- `skill_uri_allowlist: List[str] = []`

字段约束补充：

- `skill_uri_allowlist` 为 URI 前缀白名单（`uri.startswith(prefix)` 命中即允许）。
- 默认空列表表示禁用 `source_type="uri"`（安全默认）。

---

## 7) runtime/registry（CapabilityRegistry）

核心方法（对外行为要求）：

- `register(spec)`：重复 ID 覆盖
- `get(id)`：不存在返回 `None`
- `get_or_raise(id)`：不存在抛 `KeyError`
- `list_by_kind(kind)`：按 kind 返回列表
- `validate_dependencies() -> List[str]`：返回缺失依赖的 ID 列表（提取规则见 registry 文档注释）

---

## 8) runtime/guards（LoopBreakerError）

### Exception：LoopBreakerError

- 语义：全局 loop iteration 熔断，防止无限循环或异常扩张。

---

## 9) 假设（Assumptions）

- `CapabilityResult.report` 在 v0.2.0 可先定义为 `dict[str, Any]` 或 `Any`（仅要求可诊断与可序列化），更强结构可在后续版本增强，但必须先更新 spec 与测试再落地。
