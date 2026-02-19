# 配置示例（config/）

本目录提供 `agently-skills-runtime` 的**示例配置**，用于帮助你复刻运行环境与集成形态。

重要说明：
- v0.2.0 主线的 `protocol/` 与 `runtime/` 不依赖上游，离线回归可独立运行。
- 适配器（`adapters/`）是可选能力：当你需要桥接上游（Agently / skills-runtime-sdk）时，再在工作区安装上游并启用对应 adapter。
- 示例只表达“形态”，不绑定任何具体业务；不要在仓库内提交真实 secrets。

## 文件说明

- `config/default.yaml`
  - v0.2.0 `RuntimeConfig` 的 YAML 形态示例（字段以 `src/agently_skills_runtime/runtime/engine.py` 为准）。
  - 可用 `agently_skills_runtime.config.load_runtime_config()` 读取。
- `config/sdk.example.yaml`
  - 上游 SDK overlays 示例（Strict Catalog：spaces + sources + scan/injection）。
  - 仅用于表达形态；实际 schema 以上游 SDK 文档与实现为准。

## 使用方式（示例）

```python
from agently_skills_runtime.config import load_runtime_config
from agently_skills_runtime import CapabilityRuntime

cfg = load_runtime_config("config/default.yaml")
runtime = CapabilityRuntime(config=cfg)
```

## 说明与约束

- `agently_agent` 等运行期对象无法在 YAML 中表达，需由宿主代码注入（例如 `RuntimeConfig(agently_agent=...)`）。
- `preflight_mode` 仅作为字段保留：框架不定义任何人机交互概念，业务层自行决定如何消费执行结果。
