<div align="center">

[English](README.md) | [中文](README.zh-CN.md)

</div>

# config/

This directory contains example configuration shapes for `capability-runtime`.

Important boundaries:

- the repository exposes `Runtime` and `RuntimeConfig` as the public entrypoint
- example YAML files describe shapes, not secrets
- runtime-only objects such as approval providers or Agently agents are still
  injected by host code, not by static YAML

## Files

- `default.yaml`
  - Example shape for `RuntimeConfig`
  - field names must stay aligned with `src/capability_runtime/config.py`
- `sdk.example.yaml`
  - Example overlay for `skills-runtime-sdk`
  - useful for strict catalog, sources, and mention/preflight demonstrations

## Example Usage

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

## Notes

- `sdk_config_paths` should point to real overlay files controlled by the host application.
- `preflight_mode="error"` is the safest default when you want fail-closed behavior.
- never commit real `.env`, provider credentials, or environment-specific overlay files.
