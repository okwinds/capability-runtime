<div align="center">

[English](README.md) | [中文](README.zh-CN.md)

</div>

# config/

本目录提供 `capability-runtime` 的配置形态示例。

重要边界：

- 公开入口是 `Runtime` 与 `RuntimeConfig`
- YAML 只表达配置形态，不表达 secrets
- approvals provider、Agently agent 之类运行期对象仍由宿主代码注入，而不是靠静态 YAML 直接构造

## 文件说明

- `default.yaml`
  - `RuntimeConfig` 的示例形态
  - 字段必须与 `src/capability_runtime/config.py` 保持一致
- `sdk.example.yaml`
  - `skills-runtime-sdk` overlay 示例
  - 用于 strict catalog、sources、mention/preflight 等形态说明

## 使用示例

```python
from pathlib import Path

import yaml

from capability_runtime import Runtime, RuntimeConfig

raw = yaml.safe_load(Path("config/default.yaml").read_text(encoding="utf-8")) or {}
cfg = RuntimeConfig(
    mode=str(raw.get("mode") or "bridge"),
    workspace_root=Path(str(raw.get("workspace_root") or ".")),
    preflight_mode=str(raw.get("preflight_mode") or "error"),
)

runtime = Runtime(cfg)
print(runtime.validate())
```

## 说明

- `sdk_config_paths` 应由宿主侧指向真实 overlay 文件。
- `preflight_mode="error"` 是推荐的 fail-closed 默认值。
- 不要提交真实 `.env`、provider 凭证或环境专属 overlay 文件。
