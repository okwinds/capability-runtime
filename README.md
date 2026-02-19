# agently-skills-runtime

`agently-skills-runtime` 是一个**面向能力（Capability-oriented）**的运行时框架：用统一协议把 **Skill / Agent / Workflow** 三种元能力进行声明、注册、执行与组合，并通过可选适配器桥接上游能力（Agently、skills-runtime-sdk 等），且保持**上游零侵入**。

> 真相源（Source of Truth）：`instructcontext/CODEX_PROMPT.md`

## 1) 这个框架做什么 / 不做什么

做三件事（框架边界）：
- 让能力可以被声明（protocol/）
- 让能力可以被执行（runtime/）
- 让能力可以被组合（workflow 作为一种能力）

不关心（业务决定）：
- 执行结果要不要给人看、要不要修改、修改后如何继续（框架不定义人机交互）

## 2) 安装

创建并进入虚拟环境后（Python >= 3.10）：

```bash
python -m pip install -e ".[dev]"
```

说明：
- v0.2.0 主线的 `protocol/` 与 `runtime/` **不依赖上游**，可独立运行与离线回归。
- 若你要使用 `adapters/llm_backend.py`（桥接 Agently 与 skills-runtime-sdk 的传输/事件协议），请先安装上游依赖（可在同一工作区以 editable 安装），例如：
  - `python -m pip install -e ../Agently`
  - `python -m pip install -e ../skills-runtime-sdk/packages/skills-runtime-sdk-python`

## 3) 最小示例（CapabilityRuntime）

```python
import asyncio

from agently_skills_runtime import (
    AgentSpec,
    CapabilityKind,
    CapabilityRef,
    CapabilitySpec,
    CapabilityStatus,
    CapabilityRuntime,
    InputMapping,
    LoopStep,
    RuntimeConfig,
    Step,
    WorkflowSpec,
)


async def main() -> None:
    runtime = CapabilityRuntime(config=RuntimeConfig(workspace_root="."))

    runtime.register(AgentSpec(base=CapabilitySpec(id="agent-a", kind=CapabilityKind.AGENT, name="A")))
    runtime.register(AgentSpec(base=CapabilitySpec(id="agent-b", kind=CapabilityKind.AGENT, name="B"), loop_compatible=True))
    runtime.register(
        WorkflowSpec(
            base=CapabilitySpec(id="wf-main", kind=CapabilityKind.WORKFLOW, name="Main"),
            steps=[
                Step(id="plan", capability=CapabilityRef(id="agent-a")),
                LoopStep(
                    id="work",
                    capability=CapabilityRef(id="agent-b"),
                    iterate_over="step.plan.items",
                    item_input_mappings=[InputMapping(source="item", target_field="item")],
                    max_iterations=10,
                    collect_as="results",
                ),
            ],
        )
    )

    runtime.validate()
    result = await runtime.run("wf-main", context_bag={"task": "do something"})
    assert result.status in (CapabilityStatus.SUCCESS, CapabilityStatus.FAILED)


if __name__ == "__main__":
    asyncio.run(main())
```

## 4) 配置

示例配置：
- `config/default.yaml`：`RuntimeConfig` 的 YAML 形态示例
- `config/sdk.example.yaml`：上游 SDK overlays 示例（仅表达形态）

加载配置（可选）：

```python
from agently_skills_runtime.config import load_runtime_config

cfg = load_runtime_config("config/default.yaml")
```

## 5) 测试（离线回归）

```bash
pytest -q
```

## 6) 文档入口

- `instructcontext/CODEX_PROMPT.md`：重构任务规格与验收标准
- `DOCS_INDEX.md`：仓库文档索引（入口）
- `docs/specs/engineering-spec-v2/SPEC_INDEX.md`：v0.2.0 主线工程规格索引
