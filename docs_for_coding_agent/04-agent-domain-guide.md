# 从 0 构建 Agent Domain
本文面向已经掌握 `CapabilityRuntime` 基础、准备进入业务落地的编码智能体。
目标：把“能跑示例”升级为“可复制的业务域脚手架”。
## Agent Domain 是什么
Agent Domain 是业务层代码，不属于框架内核。
业务域负责：
- 定义业务所需的 `AgentSpec` / `WorkflowSpec` / `SkillSpec`
- 决定执行入口、编排策略、产物存储方式
- 决定人机协作点（human-in-loop）
- 决定是否暴露服务层（CLI/HTTP/SSE）
框架负责：
- 声明模型（Protocol）
- 注册与依赖校验（Registry）
- 执行调度（Runtime + Adapters）
- 统一结果结构（`CapabilityResult`）
边界原则：
- 业务域不要绕过 Runtime 手搓执行链
- 框架不承载具体业务语义
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
├── skills/
│   ├── __init__.py
│   └── writing_style.py
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
- `agents/`：只定义单能力输入输出
- `workflows/`：只定义数据流和步骤关系
- `skills/`：只定义注入知识/规则
- `storage/`：只处理持久化
- `registry.py`：唯一注册入口
- `main.py`：运行模式与门禁逻辑
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
        "请分析创作想法并输出结构化结果。\n"
        "raw_idea={raw_idea}\n"
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
- Skill：`skill.<domain>.<name>`
收益：
- 全局唯一 ID 更直观
- 报错可快速定位
- 跨仓库迁移冲突更少
### `{field}` 模板约束
`AgentAdapter` 内部调用 `str.format(**input)`，因此：
- 只能用 `{field}` 占位符
- 占位符名必须存在于输入字典
- 字段缺失会降级为“原模板 + 输入 JSON”
建议把复杂对象先序列化为字符串字段，再注入模板。
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
## Step 3：定义 SkillSpec（inject_to）
Skill 常用于注入可复用写作规则，不承载执行流。
```python
from agently_skills_runtime import CapabilityKind, CapabilitySpec, SkillSpec
spec = SkillSpec(
    base=CapabilitySpec(
        id="skill.content.writing_style",
        kind=CapabilityKind.SKILL,
        name="Writing Style Guide",
    ),
    source_type="inline",
    source=(
        "写作要求：\n"
        "1) 每段先结论后理由；\n"
        "2) 给出可执行建议；\n"
        "3) 避免夸张营销语气。"
    ),
    inject_to=["agent.content.angle_writer"],
)
```
关键点：
- `inject_to` 必须精确匹配 Agent ID
- Skill 注入影响 task 文本，不改变 Workflow 数据流
## Step 4：实现 registry.py
把所有能力集中登记到 `register_all(runtime)`：
```python
from agently_skills_runtime import CapabilityRuntime
from .agents import angle_writer, editor, topic_analyst
from .skills import writing_style
from .workflows import content_creation
ALL_SPECS = [
    topic_analyst.spec,
    angle_writer.spec,
    editor.spec,
    writing_style.spec,
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
## Step 5：实现 storage
最小存储接口：
- `save(run_id, step_id, data)`
- `load(run_id, step_id)`
建议路径：`artifacts/<run_id>/<step_id>.json`。
建议编码：`utf-8 + ensure_ascii=False + indent=2`。
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
        config_paths=[],
        preflight_mode="off",
        upstream_verification_mode="off",
    ),
)
runtime.set_adapter(CapabilityKind.AGENT, AgentAdapter(runner=bridge.run_async))
```
## Step 7：人机协作预留
框架不决定审批策略，业务域自行编排。
常见模式：
- 模式 A：步骤间暂停审批
- 模式 B：整条 workflow 后统一复核
## 验收清单
- [ ] `agents/workflows/skills/storage` 分层齐全
- [ ] 每个能力文件导出单一 `spec`
- [ ] `register_all()` + `validate()` 可通过
- [ ] mock 模式可离线运行并产出 artifacts
- [ ] real 模式具备安全门禁（缺条件不抛异常）
- [ ] `python -m pytest tests/ -v` 通过
## 升级路径（脚手架 -> 生产）
1. 复制 `examples/11_agent_domain_starter/` 到业务仓
2. 替换 Prompt 与字段语义
3. 用真实 bridge runner 替换 mock adapter
4. 增加关键 workflow 的回归测试
5. 拆分服务层（HTTP/SSE）并补审计
## 反模式
- 在业务 Agent 内直接调用 LLM SDK（绕过 Runtime）
- 执行与存储耦合在 Adapter 中
- 不做 `validate()` 就上线
- 在代码中硬编码密钥
## 总结
Agent Domain 的核心是“可维护业务闭环”：
- 声明可读
- 编排可追溯
- 执行可验证
- 结果可存档
先保证 mock 模式稳定产出 artifacts，再切 real 接线，是最低风险路径。
