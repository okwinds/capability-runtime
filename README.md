# agently-skills-runtime

`agently-skills-runtime` 是一个**桥接胶水层（bridge/glue layer）**：把上游 **Agently**（LLM 传输 + TriggerFlow 工作流编排）与上游 **skills-runtime-sdk**（SkillsManager + Tool dispatch + WAL/事件证据链 + Agent 引擎）组装起来，让业务层用一个稳定入口获得“可执行 + 可审计 + 可回归”的运行闭环。

> 战略回归说明：`docs/specs/engineering-spec/00_Overview/PIVOT_2026-02-19.md`

## 1) 这个框架做什么 / 不做什么

做（本仓库职责）：
- 桥接 Agently 的 OpenAICompatible requester → SDK `ChatBackend`（保持 tool_calls wire 不变量）
- 提供 TriggerFlow tool（`triggerflow_run_flow`，默认必须审批）
- 提供 preflight gate（生产默认 fail-closed）
- 聚合 SDK 事件流 → NodeReport v2（控制面强结构）

不做（上游负责）：
- 不自研 Agent 执行引擎（由 SDK Agent 执行）
- 不自研 Workflow 编排引擎（由 TriggerFlow 执行；本仓库先以 tool 触发方式集成）
- 不自研 Skills 发现/加载/治理（由 SkillsManager 负责）

## 2) 安装（开发机建议：同一工作区 editable）

创建并进入虚拟环境后（Python >= 3.10）：

```bash
python -m pip install -e ../Agently
python -m pip install -e ../skills-runtime-sdk/packages/skills-runtime-sdk-python
python -m pip install -e ".[dev]"
```

说明：
- 本仓库是胶水层，**依赖上游是正常且必要的**；没有上游就不存在“真实执行闭环”。
- 上游零侵入：本仓库不会修改上游代码，仅通过 Public API 适配。

## 3) 最小示例（AgentlySkillsRuntime）

> 注意：示例仅表达“形态”。真实运行需要你提供 Agently 的模型配置、以及（如启用 TriggerFlow tool）注入 `HumanIOProvider` 与 `TriggerFlowRunner`。

```python
import asyncio
from pathlib import Path

import agently

from agently_skills_runtime import AgentlySkillsRuntime
from agently_skills_runtime.runtime import AgentlySkillsRuntimeConfig


async def main() -> None:
    # 1) 创建 Agently agent（负责 OpenAICompatible requester / settings）
    agent = agently.Agently.create_agent()

    # 2) 创建 runtime（桥接层）
    cfg = AgentlySkillsRuntimeConfig(
        workspace_root=Path("."),
        config_paths=[],
        preflight_mode="off",  # 生产建议用 "error"
    )
    rt = AgentlySkillsRuntime(agently_agent=agent, config=cfg)

    # 3) 执行（SDK Agent 作为引擎：tool loop + WAL/事件）
    out = await rt.run_async("say hello")
    print(out.final_output)
    print(out.node_report.status, out.node_report.reason)


if __name__ == "__main__":
    asyncio.run(main())
```

## 4) 测试（离线回归）

```bash
.venv/bin/python -m pytest -q
```

## 5) 文档入口

- `DOCS_INDEX.md`：仓库文档索引（入口）
- `docs/specs/engineering-spec/SPEC_INDEX.md`：胶水层主线工程规格索引
- `docs/specs/engineering-spec/00_Overview/PIVOT_2026-02-19.md`：战略回归说明
