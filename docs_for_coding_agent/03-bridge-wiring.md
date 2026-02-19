# Bridge 接线指南：连接真实 LLM

本文用于把 `agently-skills-runtime` 从离线 mock 模式接到真实 LLM。
目标读者：需要做 Phase 4A 集成的编码智能体。

## 架构回顾

在当前仓库中，调用链如下：

```text
CapabilityRuntime
  -> AgentAdapter.execute(...)
    -> runner(task, initial_history=...)
      -> AgentlySkillsRuntime.run_async(...)
        -> Agently OpenAICompatible requester
          -> real LLM
```

关键约束：
- `AgentAdapter` 的 runner 兼容签名是：
  - `async def runner(task: str, *, initial_history=None) -> Any`
- `AgentlySkillsRuntime.run_async` 已满足该签名，可直接注入。
- 输出以 `NodeResultV2` 返回；`AgentAdapter` 会自动包装成 `CapabilityResult`。

## 接线三步法

### Step 1：配置上游 Agently

- 使用 `Agently.set_settings("OpenAICompatible", {...})`
- 至少设置 `base_url`、`model`、`auth`
- 创建宿主 agent：`Agently.create_agent()`

示例：

```python
from agently import Agently

Agently.set_settings(
    "OpenAICompatible",
    {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "auth": "<OPENAI_API_KEY>",
    },
)
agently_agent = Agently.create_agent()
```

### Step 2：构造 Bridge Runtime

- 创建 `AgentlySkillsRuntimeConfig`
- 在示例环境建议关闭 gate，避免被 preflight/upstream 校验阻断

```python
from pathlib import Path
from agently_skills_runtime import AgentlySkillsRuntime, AgentlySkillsRuntimeConfig

bridge = AgentlySkillsRuntime(
    agently_agent=agently_agent,
    config=AgentlySkillsRuntimeConfig(
        workspace_root=Path.cwd(),
        config_paths=[],
        preflight_mode="off",
        upstream_verification_mode="off",
    ),
)
```

### Step 3：构造 AgentAdapter 的 runner

由于签名已兼容，直接注入：

```python
from agently_skills_runtime import AgentAdapter

adapter = AgentAdapter(runner=bridge.run_async)
```

> 如果未来 runner 签名出现差异，优先在 `examples/10_bridge_wiring/wiring.py`（或 run.py 的 helper）做轻量适配，不修改 `src/` 主体实现。

### Step 4：组装 CapabilityRuntime

- `CapabilityRuntime` 负责声明式能力执行
- `AgentAdapter` 负责把 `AgentSpec` 映射到 bridge runner

## 完整接线代码（可运行骨架）

```python
from __future__ import annotations

import asyncio
from pathlib import Path

from agently import Agently
from agently_skills_runtime import (
    AgentIOSchema,
    AgentAdapter,
    AgentSpec,
    AgentlySkillsRuntime,
    AgentlySkillsRuntimeConfig,
    CapabilityKind,
    CapabilityRuntime,
    CapabilitySpec,
    RuntimeConfig,
)


async def main() -> None:
    Agently.set_settings(
        "OpenAICompatible",
        {
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "auth": "<OPENAI_API_KEY>",
        },
    )
    agently_agent = Agently.create_agent()

    bridge = AgentlySkillsRuntime(
        agently_agent=agently_agent,
        config=AgentlySkillsRuntimeConfig(
            workspace_root=Path.cwd(),
            config_paths=[],
            preflight_mode="off",
            upstream_verification_mode="off",
        ),
    )

    runtime = CapabilityRuntime(config=RuntimeConfig())
    runtime.set_adapter(CapabilityKind.AGENT, AgentAdapter(runner=bridge.run_async))

    runtime.register(
        AgentSpec(
            base=CapabilitySpec(
                id="agent.bridge.summary",
                kind=CapabilityKind.AGENT,
                name="Bridge Summary Agent",
            ),
            prompt_template="请用一句话总结主题：{topic}",
            system_prompt="你是简洁、准确的技术写作助手。",
            output_schema=AgentIOSchema(fields={"summary": "str"}, required=["summary"]),
        )
    )

    result = await runtime.run("agent.bridge.summary", input={"topic": "Bridge wiring"})
    print(result.status.value)
    print(str(result.output)[:200])


if __name__ == "__main__":
    asyncio.run(main())
```

## `.env.example`

建议在 `examples/10_bridge_wiring/.env.example` 保持这三项：

```dotenv
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=https://api.openai.com/v1
MODEL_NAME=gpt-4o-mini
```

运行前复制：

```bash
cp examples/10_bridge_wiring/.env.example examples/10_bridge_wiring/.env
```

## 注意事项

- runner 函数签名必须与 `AgentAdapter` 兼容：
  - `runner(task: str, *, initial_history=None)`
- Skills 文本注入（`skills_text`）与 output schema 约束由 `AgentAdapter._build_task` 负责编排到 task 文本。
- Bridge 侧 `AgentlySkillsRuntime` 在 v0.3.0 引入，v0.4.0 继续保留且兼容。
- 示例代码必须提供缺失配置时的“安全退出”路径：
  - 缺 `.env` 或关键 env -> 打印提示并退出（exit 0）
  - env 齐全但 `import agently` 失败 -> 打印安装/降级提示并退出

## 常见问题

Q: 为什么不直接使用 Agently，而要绕一层框架？

A: 因为框架层提供了声明式编排（Workflow/Loop/Parallel/Conditional）和统一返回结构（`CapabilityResult` + `NodeReport` 证据链）。直接用 Agently 时，这部分需要业务自己重复实现。

Q: 只想验证单个 Agent，还需要完整接线吗？

A: 不需要。先用 mock adapter 验证编排逻辑即可。只有在需要真实模型质量验证时再切到 bridge 接线。

Q: `run.py` 和 `run_mock_fallback.py` 为什么都保留？

A: 为了保障“任何环境都能跑”：可联网且依赖齐全时跑真实接线，不满足条件时跑离线 fallback。
