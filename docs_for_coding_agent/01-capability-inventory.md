# 01-capability-inventory（能力清单：Protocol / Runtime / Adapters）

> 面向：编码智能体 / 维护者  
> 目标：把“公共 API + 字段默认值 + 运行期语义”收敛成一份可检索清单，方便写测试、写示例、做回归。  
> 范围：以 `src/agently_skills_runtime/__init__.py` 的导出面为准；细节以 `src/` 地面真相为准。

---

## A) Protocol（纯类型契约，零上游依赖）

> 入口：`src/agently_skills_runtime/protocol/*`  
> 导出面：`src/agently_skills_runtime/protocol/__init__.py`

### A.1 `CapabilityKind`（枚举）

- 定义：`src/agently_skills_runtime/protocol/capability.py`
- 值：`skill / agent / workflow`

### A.2 `CapabilitySpec`（公共能力字段）

- 类型：`dataclass(frozen=True)`；字段与默认值：

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `id` | `str` | （必填） | 全局唯一 ID |
| `kind` | `CapabilityKind` | （必填） | 能力种类 |
| `name` | `str` | （必填） | 人类可读名称 |
| `description` | `str` | `""` | 描述可为空 |
| `version` | `str` | `"0.1.0"` | 语义化版本 |
| `tags` | `List[str]` | `[]` | 分类/检索 |
| `metadata` | `Dict[str, Any]` | `{}` | 框架不解读 |
### A.3 `CapabilityRef`（能力引用）

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `id` | `str` | （必填） | 被引用能力 ID |
| `kind` | `Optional[CapabilityKind]` | `None` | 类型提示（可选） |

### A.4 `CapabilityStatus`（执行状态）

- `pending / running / success / failed / cancelled`

### A.5 `CapabilityResult`（统一返回）

> 注意：这是 CapabilityRuntime/Adapters 的返回结构；桥接层另外有 `NodeResultV2`。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `status` | `CapabilityStatus` | （必填） | 成功/失败等 |
| `output` | `Any` | `None` | 典型是 `dict` 或 `str` |
| `error` | `Optional[str]` | `None` | 失败原因 |
| `report` | `Optional[Any]` | `None` | 可选报告（如 NodeReport） |
| `artifacts` | `List[str]` | `[]` | 产物路径列表 |
| `duration_ms` | `Optional[float]` | `None` | 耗时（ms） |
| `metadata` | `Dict[str, Any]` | `{}` | 扩展信息 |

## B) Skill（元能力：注入 + 可选调度）

> 定义：`src/agently_skills_runtime/protocol/skill.py`

### B.1 `SkillDispatchRule`

| 字段 | 类型 | 默认值 | 语义（地面真相） |
|---|---|---|---|
| `condition` | `str` | （必填） | 当前语义是 **context bag key**，以 `bool(context.bag.get(condition))` 判断 |
| `target` | `CapabilityRef` | （必填） | 被调度的目标能力 |
| `priority` | `int` | `0` | 数值越大越优先（同优先级按声明顺序） |
| `metadata` | `Dict[str, Any]` | `{}` | 扩展字段 |

### B.2 `SkillSpec`

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `base` | `CapabilitySpec` | （必填） | 公共能力字段（kind=skill） |
| `source` | `str` | （必填） | 内容来源（见 `source_type`） |
| `source_type` | `str` | `"file"` | `"file" \| "inline" \| "uri"` |
| `dispatch_rules` | `List[SkillDispatchRule]` | `[]` | 调度规则（可空） |
| `inject_to` | `List[str]` | `[]` | **Agent ID 列表**，用于自动注入 |

`source_type` 约定（Adapter 语义）：
- `file`：把 `source` 当作相对 `workspace_root` 的文件路径
- `inline`：把 `source` 当作正文文本
- `uri`：默认禁用（安全原因，需要 allowlist 才能启用）

## C) Agent（元能力：被 Adapter 委托执行）

> 定义：`src/agently_skills_runtime/protocol/agent.py`

### C.1 `AgentIOSchema`

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `fields` | `Dict[str, str]` | `{}` | 字段名 → 类型描述 |
| `required` | `List[str]` | `[]` | 必填字段名列表 |

### C.2 `AgentSpec`

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `base` | `CapabilitySpec` | （必填） | 公共能力字段（kind=agent） |
| `skills` | `List[str]` | `[]` | 显式装载 Skill ID 列表 |
| `tools` | `List[str]` | `[]` | Tool 名称列表（桥接层可用） |
| `collaborators` | `List[CapabilityRef]` | `[]` | 可协作 Agent 引用 |
| `callable_workflows` | `List[CapabilityRef]` | `[]` | 可调用 Workflow 引用 |
| `input_schema` | `Optional[AgentIOSchema]` | `None` | 输入 schema（可选） |
| `output_schema` | `Optional[AgentIOSchema]` | `None` | 输出 schema（可选） |
| `loop_compatible` | `bool` | `False` | 是否可被 LoopStep 调用 |
| `llm_config` | `Optional[Dict[str, Any]]` | `None` | LLM 覆盖配置（桥接层可用） |
| `prompt_template` | `Optional[str]` | `None` | `{field}` 占位符模板 |
| `system_prompt` | `Optional[str]` | `None` | system prompt（桥接层可用） |

## D) Workflow（元能力：编排 Step/Loop/Parallel/Conditional）

> 定义：`src/agently_skills_runtime/protocol/workflow.py`

### D.1 `InputMapping`

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `source` | `str` | （必填） | 数据源表达式 |
| `target_field` | `str` | （必填） | 目标输入字段名 |

### D.2 `Step`

| 字段 | 类型 | 默认值 |
|---|---|---|
| `id` | `str` | （必填） |
| `capability` | `CapabilityRef` | （必填） |
| `input_mappings` | `List[InputMapping]` | `[]` |

### D.3 `LoopStep`

| 字段 | 类型 | 默认值 |
|---|---|---|
| `id` | `str` | （必填） |
| `capability` | `CapabilityRef` | （必填） |
| `iterate_over` | `str` | （必填） |
| `item_input_mappings` | `List[InputMapping]` | `[]` |
| `max_iterations` | `int` | `100` |
| `collect_as` | `str` | `"results"` |
| `fail_strategy` | `str` | `"abort"`（也可 `skip/collect`） |

### D.4 `ParallelStep`

| 字段 | 类型 | 默认值 |
|---|---|---|
| `id` | `str` | （必填） |
| `branches` | `List[Step \| LoopStep]` | `[]` |
| `join_strategy` | `str` | `"all_success"`（也可 `any_success/best_effort`） |

### D.5 `ConditionalStep`

| 字段 | 类型 | 默认值 |
|---|---|---|
| `id` | `str` | （必填） |
| `condition_source` | `str` | （必填） |
| `branches` | `Dict[str, Step \| LoopStep]` | `{}` |
| `default` | `Optional[Step \| LoopStep]` | `None` |

### D.6 `WorkflowSpec`

| 字段 | 类型 | 默认值 |
|---|---|---|
| `base` | `CapabilitySpec` | （必填） |
| `steps` | `List[WorkflowStep]` | `[]` |
| `context_schema` | `Optional[Dict[str, str]]` | `None` |
| `output_mappings` | `List[InputMapping]` | `[]` |

## E) ExecutionContext（跨能力状态传递 + 调用链）

> 定义：`src/agently_skills_runtime/protocol/context.py`

### E.1 `ExecutionContext` 字段与默认值

| 字段 | 类型 | 默认值 |
|---|---|---|
| `run_id` | `str` | （必填） |
| `parent_context` | `Optional[ExecutionContext]` | `None` |
| `depth` | `int` | `0` |
| `max_depth` | `int` | `10` |
| `bag` | `Dict[str, Any]` | `{}` |
| `step_outputs` | `Dict[str, Any]` | `{}` |
| `call_chain` | `List[str]` | `[]` |

### E.2 `resolve_mapping(expression)` 支持的前缀

- `context.{key}`
- `previous.{key}`
- `step.{step_id}.{key}` / `step.{step_id}`
- `literal.{value}`
- `item` / `item.{key}`（LoopStep 迭代内）

约束（非常重要）：
- 找不到时返回 `None`（不抛异常）

## F) Runtime（注册/校验/调度/护栏）

> 入口：`src/agently_skills_runtime/runtime/*`  
> 导出面：`src/agently_skills_runtime/runtime/__init__.py`

### F.1 `RuntimeConfig`

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `max_depth` | `int` | `10` | 递归深度护栏 |
| `max_total_loop_iterations` | `int` | `50000` | 全局 loop 熔断 |
| `default_loop_max_iterations` | `int` | `200` | **保留字段**：当前 `WorkflowAdapter` 未读取它 |

地面真相提示：  
当前 Loop 的实际默认值来自 `LoopStep.max_iterations == 100`（协议层默认）。

### F.2 `CapabilityRegistry`（能力注册表）

常用方法（语义摘要）：
- `register(spec)`：重复 ID 覆盖（last-write-wins）
- `get(id)` / `get_or_raise(id)`
- `validate_dependencies()`：返回缺失依赖 ID 列表（排序后）
- `find_skills_injecting_to(agent_id)`：返回 `inject_to` 包含该 Agent ID 的所有 `SkillSpec`

### F.3 `ExecutionGuards`（全局迭代熔断）

| 方法/属性 | 说明 |
|---|---|
| `tick()` | 每次迭代调用一次，超限抛 `LoopBreakerError` |
| `reset()` | 顶层 run 前重置 |
| `counter` | 当前累计迭代次数 |

### F.4 `LoopController.run_loop(...)`

签名（摘要）：
- `items: List[Any]`
- `max_iterations: int`
- `execute_fn: (item, idx) -> CapabilityResult`
- `fail_strategy: "abort" | "skip" | "collect"`

返回：
- `CapabilityResult.output` 是结果列表
- `metadata.completed_iterations/total_planned/skipped_errors`

### F.5 `AdapterProtocol.execute(...)`

Adapter 必须实现：

- `async def execute(*, spec, input: Dict[str, Any], context: ExecutionContext, runtime: CapabilityRuntime) -> CapabilityResult`

### F.6 `CapabilityRuntime`

生命周期（必须按顺序）：
1. `rt = CapabilityRuntime(config=RuntimeConfig())`
2. `rt.set_adapter(kind, adapter)`
3. `rt.register(spec)` / `rt.register_many(specs)`
4. `missing = rt.validate()`（空列表才可安全 run）
5. `result = await rt.run(capability_id, input=..., context_bag=...)`

`run()` 的失败形态（metadata.error_type）：
- `not_found`：未注册 capability_id
- `no_adapter`：未注入该 kind 的 adapter
- `recursion_limit`：嵌套深度超限
- `loop_breaker`：全局循环熔断
- `adapter_error`：adapter 抛异常

## G) Adapters（把声明变成可执行）

> 入口：`src/agently_skills_runtime/adapters/*_adapter.py`  
> 导出面：`src/agently_skills_runtime/adapters/__init__.py`

### G.1 `SkillAdapter`（内容加载 + dispatch_rules）

地面真相（关键语义）：
- 执行成功时 `CapabilityResult.output == content(str)`
- `dispatch_rules` 命中时，调度结果写入 `CapabilityResult.metadata["dispatched"]`
- `condition` 的判断：`bool(context.bag.get(condition))`

### G.2 `AgentAdapter`（Skill 合并注入 + runner 委托）

地面真相（关键语义）：
- 若未注入 `runner`：直接返回 FAILED（error 文本明确）
- 合并 skill IDs：`spec.skills + registry.find_skills_injecting_to(spec.base.id)`
- Skill 内容默认取 `SkillSpec.source`（除非注入 `skill_content_loader`）
- `prompt_template` 存在时优先 `.format(**input)`；缺 key 则退化为“模板 + 输入 JSON”

### G.3 `WorkflowAdapter`（Step 编排）

地面真相（关键语义）：
- 执行开始时：`context.bag.update(input)`
- 每步输出：写入 `context.step_outputs[step.id] = result.output`
- 若 `WorkflowSpec.output_mappings` 为空：最终输出是 `dict(context.step_outputs)`
- LoopStep：
  - `iterate_over` 必须解析为 `list`，否则 FAILED
  - 迭代内当前元素放入 `bag["__current_item__"]`，供 `item/item.{key}` 读取

## H) Errors（统一错误）

> 定义：`src/agently_skills_runtime/errors.py`（以及 `protocol/context.py`）

- `AgentlySkillsRuntimeError` / `AdapterNotFoundError` / `CapabilityNotFoundError` / `RecursionLimitError`
