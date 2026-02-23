# 从 0 构建 Agent Domain（方案2：Agent/Workflow 原语 + agent_sdk skills）

本文面向已经掌握 `CapabilityRuntime` 基础、准备进入业务落地的编码智能体。  
目标：把“能跑示例”升级为“可复制的业务域脚手架”。

## Agent Domain 是什么

Agent Domain 是业务层代码，不属于框架内核。

业务域负责：

- 定义业务所需的 `AgentSpec` / `WorkflowSpec`
- （可选）通过 `agent_sdk` 的配置（YAML overlays）声明 skills（Strict Catalog + sources）
- 决定执行入口、编排策略、产物存储方式
- 决定人机协作点（human-in-loop）
- 决定是否暴露服务层（CLI/HTTP/SSE）

框架负责：

- 声明模型（Protocol）
- 注册与依赖校验（Registry）
- 执行调度（Runtime + Adapters）
- 统一结果结构（`CapabilityResult`）
- 上游桥接与证据链聚合（`AgentlySkillsRuntime` / NodeReport）

边界原则：

- 业务域不要绕过 Runtime 手搓执行链
- 框架不承载具体业务语义
- 方案2：业务域不要在本仓 Protocol 里定义 `SkillSpec`（skills 以 `agent_sdk` 为真相源）

---

## 推荐目录结构

从 `examples/11_agent_domain_starter/` 复制即可：

```text
agent_domain/
├── agents/
│   ├── __init__.py
│   ├── topic_analyst.py
│   ├── angle_writer.py
│   └── editor.py
├── workflows/
│   ├── __init__.py
│   └── content_creation.py
├── configs/               # 可选：agent_sdk YAML overlays（skills catalog/sources 等）
│   └── skills.dev.yaml
├── storage/
│   ├── __init__.py
│   └── file_store.py
├── registry.py
├── mock_adapter.py
├── main.py
├── README.md
└── .env.example
```

分层职责：

- `agents/`：只定义单能力输入输出（“做什么”）
- `workflows/`：只定义数据流和步骤关系（“怎么编排”）
- `configs/`：只放配置（“skills 如何治理/加载”）
- `storage/`：只处理持久化
- `registry.py`：唯一注册入口
- `main.py`：运行模式与门禁逻辑

---

## Step 1：定义 AgentSpec

每个 Agent 一个文件，导出一个 `spec`。

```python
from agently_skills_runtime import AgentIOSchema, AgentSpec, CapabilityKind, CapabilitySpec
spec = AgentSpec(
    base=CapabilitySpec(
        id="agent.content.topic_analyst",
        kind=CapabilityKind.AGENT,
        name="Topic Analyst",
        description="把原始想法提炼成选题和角度",
        tags=["content", "analysis"],
    ),
    system_prompt="你是资深内容策略师，输出结构化且可执行。",
    prompt_template=(
        "请分析创作想法并输出结构化结果。\\n"
        "raw_idea={raw_idea}\\n"
        "audience={audience}"
    ),
    output_schema=AgentIOSchema(
        fields={"topic": "str", "angles": "list[str]", "reasoning": "str"},
        required=["topic", "angles"],
    ),
)
```

命名建议：

- Agent：`agent.<domain>.<name>`
- Workflow：`workflow.<domain>.<name>`

### `{field}` 模板约束

`AgentAdapter` 内部调用 `str.format(**input)`，因此：

- 只能用 `{field}` 占位符
- 占位符名必须存在于输入字典
- 字段缺失会降级为“原模板 + 输入 JSON”

建议把复杂对象先序列化为字符串字段，再注入模板。

---

## Step 2：定义 WorkflowSpec

Workflow 是业务闭环主干，先保证数据流连通。

```python
from agently_skills_runtime import (
    CapabilityKind,
    CapabilityRef,
    CapabilitySpec,
    InputMapping,
    LoopStep,
    Step,
    WorkflowSpec,
)
spec = WorkflowSpec(
    base=CapabilitySpec(
        id="workflow.content.creation",
        kind=CapabilityKind.WORKFLOW,
        name="Content Creation Workflow",
    ),
    steps=[
        Step(
            id="analyze",
            capability=CapabilityRef(id="agent.content.topic_analyst"),
            input_mappings=[
                InputMapping(source="context.raw_idea", target_field="raw_idea"),
                InputMapping(source="context.audience", target_field="audience"),
            ],
        ),
        LoopStep(
            id="write_sections",
            capability=CapabilityRef(id="agent.content.angle_writer"),
            iterate_over="step.analyze.angles",
            item_input_mappings=[
                InputMapping(source="item", target_field="angle"),
                InputMapping(source="step.analyze.topic", target_field="topic"),
                InputMapping(source="context.audience", target_field="audience"),
            ],
            max_iterations=10,
        ),
        Step(
            id="edit",
            capability=CapabilityRef(id="agent.content.editor"),
            input_mappings=[
                InputMapping(source="step.analyze.topic", target_field="topic"),
                InputMapping(source="step.write_sections", target_field="sections"),
                InputMapping(source="context.target_length", target_field="target_length"),
            ],
        ),
    ],
    output_mappings=[
        InputMapping(source="step.analyze", target_field="analysis"),
        InputMapping(source="step.write_sections", target_field="sections"),
        InputMapping(source="step.edit", target_field="final"),
    ],
)
```

InputMapping 前缀速查：

- `context.{key}`：读取顶层输入
- `previous.{key}`：读取上一步输出字段
- `step.{step_id}.{key}`：读取指定步骤字段
- `step.{step_id}`：读取指定步骤整体
- `literal.{value}`：字面量字符串
- `item` / `item.{key}`：循环项

注意：前缀拼错不会抛异常，只会得到 `None`。

---

## Step 3（可选）：接入 skills（`agent_sdk`）

方案2里，本仓库不再提供 `SkillSpec/SkillAdapter`。如果业务要用 skills：

1) 用 `agent_sdk` 的 YAML overlays 声明 Strict Catalog + sources  
2) 在 task/prompt 中使用 strict mention（例如 `$[space:domain].skill_name`）  
3) 在 Host/入口处调用 `AgentlySkillsRuntime.preflight()` / `preflight_or_raise()` 做门禁

参考文档：

- `docs/internal/specs/engineering-spec/02_Technical_Design/SKILLS_SYSTEM.md`
- `docs/internal/specs/engineering-spec/02_Technical_Design/SKILLS_PREFLIGHT.md`
- `docs/internal/specs/engineering-spec/04_Operations/CONFIGURATION.md`

---

## Step 4：实现 registry.py

把所有能力集中登记到 `register_all(runtime)`：

```python
from agently_skills_runtime import CapabilityRuntime
from .agents import angle_writer, editor, topic_analyst
from .workflows import content_creation

ALL_SPECS = [
    topic_analyst.spec,
    angle_writer.spec,
    editor.spec,
    content_creation.spec,
]

def register_all(runtime: CapabilityRuntime) -> None:
    runtime.register_many(ALL_SPECS)
    missing = runtime.validate()
    if missing:
        raise RuntimeError(f"Missing capabilities: {missing}")
```

收益：

- 注册逻辑只维护一处
- main/测试/服务层都能复用

---

## Step 5：实现 storage

最小存储接口：

- `save(run_id, step_id, data)`
- `load(run_id, step_id)`

建议路径：`artifacts/<run_id>/<step_id>.json`。  
建议编码：`utf-8 + ensure_ascii=False + indent=2`。

---

## Step 6：实现 main.py（--mock / --real）

推荐行为：

- `--mock`：默认离线可运行
- `--real`：真实接线 Agently
- 缺 `.env` / 缺 env / `import agently` 失败：提示后 exit 0

真实接线核心：

```python
Agently.set_settings(
    "OpenAICompatible",
    {
        "base_url": os.environ["OPENAI_BASE_URL"],
        "model": os.environ["MODEL_NAME"],
        "auth": os.environ["OPENAI_API_KEY"],
    },
)
bridge = AgentlySkillsRuntime(
    agently_agent=Agently.create_agent(),
    config=AgentlySkillsRuntimeConfig(
        workspace_root=Path.cwd(),
        config_paths=[],  # 放 agent_sdk overlays（含 skills 配置）
        preflight_mode="off",
        upstream_verification_mode="off",
    ),
)
runtime.set_adapter(CapabilityKind.AGENT, AgentAdapter(runner=bridge.run_async))
```

---

## 验收清单

- [ ] `agents/workflows/storage` 分层齐全
- [ ] 每个能力文件导出单一 `spec`
- [ ] `register_all()` + `validate()` 可通过
- [ ] mock 模式可离线运行并产出 artifacts
- [ ] real 模式具备安全门禁（缺条件不抛异常）
- [ ] `python -m pytest tests/ -v` 通过

---

## 反模式

- 在业务 Agent 内直接调用 LLM SDK（绕过 Runtime）
- 执行与存储耦合在 Adapter 中
- 不做 `validate()` 就上线
- 在代码中硬编码密钥

