# 配置示例（config/）

本目录提供 `agently-skills-runtime` 的**示例配置**，用于帮助你复刻运行环境与集成形态。

重要说明：
- 本仓对外只承诺**单一入口**：`Runtime` + `RuntimeConfig`（从包根导入）。
- 示例只表达“形态”，不绑定任何具体业务；不要在仓库内提交真实 secrets。

## 文件说明

- `config/default.yaml`
  - `RuntimeConfig` 的 YAML 形态示例（字段以 `src/agently_skills_runtime/config.py` 为准）。
  - 本仓不强制提供“YAML → RuntimeConfig”的内置装载器；建议由宿主按自己的配置系统解析后再构造 `RuntimeConfig`。
- `config/sdk.example.yaml`
  - 上游 `skills-runtime-sdk` overlays 示例（Strict Catalog：spaces + sources + scan/mention）。
  - 仅用于表达形态；实际 schema 以上游 SDK 文档与实现为准。

## 使用方式（示例）

```python
import asyncio
from pathlib import Path

import yaml

from agently_skills_runtime import Runtime, RuntimeConfig

# 1) 读取 YAML（示例）
raw = yaml.safe_load(Path("config/default.yaml").read_text(encoding="utf-8")) or {}
sdk_paths = [Path(p) for p in (raw.get("sdk_config_paths") or [])]

# 2) 构造 RuntimeConfig（Path 类型建议在宿主侧统一 expanduser/resolve）
cfg = RuntimeConfig(
    mode=str(raw.get("mode") or "bridge"),
    workspace_root=Path(str(raw.get("workspace_root") or ".")),
    sdk_config_paths=sdk_paths,
    preflight_mode=str(raw.get("preflight_mode") or "error"),
)

# 3) 创建 Runtime（运行期对象如 agently_agent / approval_provider 等由宿主注入）
rt = Runtime(cfg)
print(rt.validate())

# 4) 执行（示例）
asyncio.run(rt.run("your-capability-id", input={}))
```

## 说明与约束

- `agently_agent` / `ApprovalProvider` / `HumanIOProvider` / `ExecSessionsProvider` 等运行期对象无法在 YAML 中表达，需由宿主代码注入。
- `preflight_mode="error"` 为生产建议默认值：发现 Skills 配置问题应 fail-closed。
