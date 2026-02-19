# 配置示例（config/）

本目录提供 `agently-skills-runtime` 的**示例配置**，用于帮助你复刻运行环境与集成形态。

重要说明：
- v0.3.0 主线为**胶水层（bridge/glue layer）**：依赖上游 Agently + skills-runtime-sdk，以获得真实执行闭环（LLM/TriggerFlow + skills/tools/WAL/事件）。
- 示例只表达“形态”，不绑定任何具体业务；不要在仓库内提交真实 secrets。

## 文件说明

- `config/default.yaml`
  - v0.3.0 bridge 配置（`BridgeConfigModel`）的 YAML 形态示例（字段以 `src/agently_skills_runtime/config.py` 为准）。
  - 用法：宿主读取 YAML → 构造 `BridgeConfigModel` → `to_runtime_config()` → 再把 paths 解析为 `AgentlySkillsRuntimeConfig`（Path 类型）。
- `config/sdk.example.yaml`
  - 上游 SDK overlays 示例（Strict Catalog：spaces + sources + scan/injection）。
  - 仅用于表达形态；实际 schema 以上游 SDK 文档与实现为准。

## 使用方式（示例）

```python
from pathlib import Path

import yaml

from agently_skills_runtime.runtime import AgentlySkillsRuntime, AgentlySkillsRuntimeConfig
from agently_skills_runtime.config import BridgeConfigModel, resolve_paths

# 1) 读取 YAML（示例）
raw = yaml.safe_load(Path("config/default.yaml").read_text(encoding="utf-8")) or {}
bridge_cfg = BridgeConfigModel.model_validate(raw)

# 2) 解析 overlays 路径，并构造运行期 config（Path）
config_paths = resolve_paths(workspace_root=Path(bridge_cfg.workspace_root), sdk_config_paths=bridge_cfg.sdk_config_paths)
rt_cfg = AgentlySkillsRuntimeConfig(
    workspace_root=Path(bridge_cfg.workspace_root),
    config_paths=config_paths,
    preflight_mode=bridge_cfg.preflight_mode,
    backend_mode=bridge_cfg.backend_mode,
    upstream_verification_mode=bridge_cfg.upstream_verification_mode,
    agently_fork_root=Path(bridge_cfg.agently_fork_root) if bridge_cfg.agently_fork_root else None,
    skills_runtime_sdk_fork_root=Path(bridge_cfg.skills_runtime_sdk_fork_root) if bridge_cfg.skills_runtime_sdk_fork_root else None,
)

# 3) 创建 runtime（运行期对象如 agently_agent / human_io 等由宿主注入）
rt = AgentlySkillsRuntime(agently_agent=object(), config=rt_cfg)
```

## 说明与约束

- `agently_agent` / `HumanIOProvider` / `TriggerFlowRunner` 等运行期对象无法在 YAML 中表达，需由宿主代码注入。
- `preflight_mode="error"` 为生产建议默认值：发现 Skills 配置问题应 fail-closed。
