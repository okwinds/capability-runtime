# BATCH 4 指令：业务域指南 + 业务脚手架示例（11）

> **前置条件**：BATCH 1-3 已交付并验证通过。
>
> **目标**：给出"如何从 0 构建一个 Agent Domain（业务域）"的完整指南和脚手架。
> 这是框架从"通用工具"变为"业务可用"的最后一步。
>
> **特殊说明**：本 BATCH 的示例可以使用业务化的场景名称（但不限定为"漫剧"），
> 目标是展示一个**通用的业务域脚手架**，让业务开发者可以复制后填入自己的 Agent 定义。

---

## 产出 1：`docs_for_coding_agent/04-agent-domain-guide.md`

### 要求

- 标题：**从 0 构建 Agent Domain**
- 面向"已经学会框架基础，准备用框架做业务"的编码智能体
- 总长度 200-300 行

### 结构模板

```markdown
# 从 0 构建 Agent Domain

## Agent Domain 是什么

Agent Domain 是**业务层代码**，不属于框架。
它的职责：
- 定义业务需要的所有 AgentSpec / WorkflowSpec / SkillSpec
- 实现制品存储（artifact storage）
- 实现人机交互编排（human-in-loop orchestration）
- 提供 REST/SSE 服务层（可选）

框架只提供：声明 → 注册 → 校验 → 执行。
Agent Domain 决定：用什么声明、何时执行、结果存哪里、何时让人介入。

## 目录结构约定

```
agent_domain/
├── agents/               # AgentSpec 定义
│   ├── __init__.py
│   ├── topic_analyst.py  # 每个 Agent 一个文件，导出 AgentSpec 实例
│   ├── writer.py
│   └── ...
│
├── workflows/            # WorkflowSpec 定义
│   ├── __init__.py
│   └── content_creation.py
│
├── skills/               # SkillSpec 定义
│   ├── __init__.py
│   └── writing_style.py
│
├── registry.py           # register_all(runtime) 一键注册
│
├── storage/              # 制品存储
│   ├── __init__.py
│   └── file_store.py    # 基于文件系统的简单 JSON 存储
│
├── main.py               # 入口：组装 runtime + 执行
└── README.md
```

## Step 1：定义 AgentSpec

### 模板

```python
"""agents/topic_analyst.py"""
from agently_skills_runtime.protocol.capability import CapabilitySpec, CapabilityKind
from agently_skills_runtime.protocol.agent import AgentSpec

spec = AgentSpec(
    base=CapabilitySpec(
        id="topic-analyst",
        kind=CapabilityKind.AGENT,
        name="Topic Analyst",
        description="Analyze raw ideas and extract structured topics.",
        tags=["analysis", "ideation"],
    ),
    system_prompt="You are a senior content strategist...",
    prompt_template="Analyze the following idea and extract...\n\nIdea: {input.raw_idea}",
    output_schema={
        "topic": "str: the refined topic",
        "angles": ["str: list of content angles"],
        "confidence": "float: confidence score 0-1",
    },
    loop_compatible=False,
)
```

### 命名约定
- id：kebab-case，全局唯一
- 文件名：snake_case，与 id 对应
- 一个文件导出一个 `spec` 变量

## Step 2：定义 WorkflowSpec

### 模板

```python
"""workflows/content_creation.py"""
from agently_skills_runtime.protocol.capability import CapabilitySpec, CapabilityKind, CapabilityRef
from agently_skills_runtime.protocol.workflow import (
    WorkflowSpec, Step, LoopStep, InputMapping,
)

spec = WorkflowSpec(
    base=CapabilitySpec(
        id="content-creation",
        kind=CapabilityKind.WORKFLOW,
        name="Content Creation Pipeline",
    ),
    steps=[
        Step(
            id="analyze",
            capability=CapabilityRef(id="topic-analyst"),
            input_mappings=[
                InputMapping(source="context.raw_idea", target_field="raw_idea"),
            ],
        ),
        LoopStep(
            id="develop",
            capability=CapabilityRef(id="angle-writer"),
            iterate_over="step.analyze.angles",
            item_input_mappings=[
                InputMapping(source="item", target_field="angle"),
                InputMapping(source="step.analyze.topic", target_field="topic"),
            ],
            max_iterations=10,
        ),
        Step(
            id="edit",
            capability=CapabilityRef(id="editor"),
            input_mappings=[
                InputMapping(source="step.develop", target_field="sections"),
                InputMapping(source="step.analyze.topic", target_field="topic"),
            ],
        ),
    ],
    output_mappings=[
        InputMapping(source="step.analyze", target_field="analysis"),
        InputMapping(source="step.develop", target_field="sections"),
        InputMapping(source="step.edit", target_field="final_draft"),
    ],
)
```

## Step 3：实现 registry.py

```python
"""registry.py — 一键注册所有能力。"""
from agently_skills_runtime.runtime.engine import CapabilityRuntime

from .agents import topic_analyst, angle_writer, editor
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

## Step 4：实现 storage（最小化）

```python
"""storage/file_store.py"""
import json
from pathlib import Path

class FileStore:
    def __init__(self, base_dir: str = "./artifacts"):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    def save(self, run_id: str, step_id: str, data: dict) -> Path:
        path = self.base / run_id / f"{step_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        return path

    def load(self, run_id: str, step_id: str) -> dict | None:
        path = self.base / run_id / f"{step_id}.json"
        if path.exists():
            return json.loads(path.read_text())
        return None
```

## Step 5：实现 main.py

```python
"""main.py — Agent Domain 入口。"""
import asyncio
from agently_skills_runtime.runtime.engine import CapabilityRuntime, RuntimeConfig
from agently_skills_runtime.adapters.workflow_adapter import WorkflowAdapter
# from .wiring import create_bridge_adapter  # 真实 LLM 接线
from .registry import register_all
from .storage.file_store import FileStore

async def main():
    # 组装
    rt = CapabilityRuntime(config=RuntimeConfig(max_depth=10))
    rt.set_adapter(CapabilityKind.WORKFLOW, WorkflowAdapter())
    # rt.set_adapter(CapabilityKind.AGENT, create_bridge_adapter())  # 真实
    rt.set_adapter(CapabilityKind.AGENT, MockAdapter())  # 开发阶段用 mock
    register_all(rt)

    # 执行
    store = FileStore()
    result = await rt.run(
        "content-creation",
        context_bag={"raw_idea": "The future of personal AI assistants"},
    )

    # 存储
    store.save(result.metadata.get("run_id", "unknown"), "final", result.output)
    print(f"Status: {result.status}")
    print(f"Output: {json.dumps(result.output, indent=2)}")

asyncio.run(main())
```

## Step 6：人机交互编排（预留）

框架不管人机交互。业务层自行编排：

```python
# 方式 A：步骤间暂停
result1 = await rt.run("topic-analyst", input={...})
store.save(run_id, "step1", result1.output)

# → 前端展示 result1，用户审核/修改
modified = await wait_for_human_approval(run_id, "step1")

# → 继续执行
result2 = await rt.run("angle-writer", input=modified)
```

```python
# 方式 B：一口气执行 Workflow，事后审核
result = await rt.run("content-creation", context_bag={...})
# → 如果不满意，修改输入重新执行
```

## 从脚手架到真实业务的路径

1. 复制 `examples/11_agent_domain_starter/` 为 `agent_domain/`
2. 用真实的 Prompt 替换模板 Prompt
3. 用 bridge_runner 替换 MockAdapter
4. 添加更多 Agent 和 Workflow
5. 添加 REST/SSE 服务层
6. 添加前端对接
```

---

## 产出 2：`examples/11_agent_domain_starter/`

**演示**：一个可直接复制使用的业务域脚手架。

**文件结构**：
```
examples/11_agent_domain_starter/
├── README.md
├── agents/
│   ├── __init__.py
│   ├── topic_analyst.py      # AgentSpec: 选题分析
│   ├── angle_writer.py       # AgentSpec: 角度写作（loop_compatible=True）
│   └── editor.py             # AgentSpec: 编辑整合
├── workflows/
│   ├── __init__.py
│   └── content_creation.py   # WorkflowSpec: 内容创作流水线
├── skills/
│   ├── __init__.py
│   └── writing_style.py      # SkillSpec: 写作风格指南
├── storage/
│   ├── __init__.py
│   └── file_store.py         # 最小文件存储
├── registry.py               # register_all(runtime)
├── mock_adapter.py           # 开发阶段用的 mock
├── main.py                   # 入口
└── .env.example              # 真实 LLM 接线时的环境变量
```

**各文件要求**：

- **agents/*.py**：每个文件导出 `spec = AgentSpec(...)`，包含有意义的 system_prompt 和 output_schema
- **workflows/content_creation.py**：导出 `spec = WorkflowSpec(...)`，编排 3 个 Agent（顺序 + 循环）
- **skills/writing_style.py**：导出 `spec = SkillSpec(...)`，inject_to 指向 writer agent
- **registry.py**：导出 `register_all(runtime)` 函数
- **storage/file_store.py**：同上述指南中的 FileStore
- **mock_adapter.py**：一个较完整的 mock adapter，按 agent_id 返回不同结构的输出
- **main.py**：组装 runtime + 注册 + 执行 + 存储，支持 `--mock` / `--real` 参数

**总代码量**：~300-400 行（跨所有文件）

**README.md 要点**：
- 这是一个业务域脚手架，可直接复制使用
- 如何运行（mock 模式 / 真实 LLM 模式）
- 如何扩展（添加 Agent / 添加 Workflow / 替换存储）
- 目录结构约定

---

## 产出 3：`docs_for_coding_agent/contract.md`

### 要求

- 标题：**编码任务契约：使用 agently-skills-runtime 的标准流程**
- 这是给编码智能体的"行为准则"——当它接到使用本框架的任务时应怎么做
- 总长度 80-120 行

### 内容

```markdown
# 编码任务契约

## 收到任务后的标准流程

1. 读 `docs_for_coding_agent/cheatsheet.md` — 建立核心 API 心智模型
2. 判断任务类型：
   - 定义新 Agent → 参考 `examples/11_agent_domain_starter/agents/`
   - 编排新 Workflow → 参考 `examples/02-05` + `examples/09`
   - 接线真实 LLM → 参考 `examples/10_bridge_wiring/`
   - 构建完整业务域 → 参考 `docs_for_coding_agent/04-agent-domain-guide.md`
3. 实现代码（遵循以下约束）
4. 写离线测试
5. 验证通过：`python -m pytest tests/ -v`

## 声明能力时的检查清单

- [ ] CapabilitySpec.id 全局唯一
- [ ] CapabilitySpec.kind 正确（SKILL/AGENT/WORKFLOW）
- [ ] AgentSpec 如果会在 LoopStep 中使用，设置 loop_compatible=True
- [ ] WorkflowSpec.steps 中的 CapabilityRef.id 都已注册
- [ ] InputMapping.source 使用正确的前缀（6 种之一）
- [ ] LoopStep.iterate_over 指向的字段确实是列表
- [ ] 调用 rt.validate() 并断言无缺失

## 编排 Workflow 时的检查清单

- [ ] 每个 Step 有唯一 id
- [ ] InputMapping 的数据流是连通的（不存在悬空引用）
- [ ] LoopStep 设置了合理的 max_iterations
- [ ] 嵌套深度不超过 RuntimeConfig.max_depth
- [ ] output_mappings 收集了所有需要的最终输出

## 常见错误及修复

| 错误现象 | 原因 | 修复 |
|----------|------|------|
| "Capability not found: X" | X 未注册 | 检查 register_all() 是否包含 X |
| "Recursion depth N exceeds max M" | 嵌套太深 | 减少嵌套层级或增大 max_depth |
| LoopStep 输出为空列表 | iterate_over 指向了 None | 检查上游步骤的输出字段名 |
| InputMapping 得到 None | source 前缀拼错 | 核对 6 种前缀的精确格式 |
| 全局循环熔断 | 循环总次数超过 50000 | 减少列表长度或 max_iterations |

## 绝对禁止

- ❌ 直接 import Agently 或 SDK（应通过 Adapter）
- ❌ 在 Workflow 内部手动调用 LLM（应通过 runtime._execute 递归）
- ❌ 在 protocol/ 层 import 上游包
- ❌ 跳过 validate()
- ❌ 修改 src/agently_skills_runtime/ 中的框架代码（除非任务明确要求）
```

---

## 交付清单

```
docs_for_coding_agent/
├── 04-agent-domain-guide.md           ✅
└── contract.md                        ✅

examples/
└── 11_agent_domain_starter/
    ├── README.md                      ✅
    ├── agents/
    │   ├── __init__.py                ✅
    │   ├── topic_analyst.py           ✅
    │   ├── angle_writer.py            ✅
    │   └── editor.py                  ✅
    ├── workflows/
    │   ├── __init__.py                ✅
    │   └── content_creation.py        ✅
    ├── skills/
    │   ├── __init__.py                ✅
    │   └── writing_style.py           ✅
    ├── storage/
    │   ├── __init__.py                ✅
    │   └── file_store.py              ✅
    ├── registry.py                    ✅
    ├── mock_adapter.py                ✅
    ├── main.py                        ✅
    └── .env.example                   ✅
```

**验证**：
```bash
# 运行脚手架（mock 模式）
python examples/11_agent_domain_starter/main.py --mock

# 检查存储产出
ls artifacts/

# 回归
python -m pytest tests/ -v
```
