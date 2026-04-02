<div align="center">

[English](02-config-reference.md) | [中文](02-config-reference.zh-CN.md)

</div>

# Config Reference

The public config object is `RuntimeConfig`.

Core fields:

- `mode`: `mock`, `bridge`, or `sdk_native`
- `workspace_root`: root for WAL and runtime state
- `sdk_config_paths`: paths to `skills-runtime-sdk` overlays
- `custom_tools`: host-registered tools injected at runtime
- `preflight_mode`: `error`, `warn`, or `off`
- `sdk_backend`: optional backend injection for offline testing
- `workflow_engine`: optional workflow-engine injection
- `runtime_client` / `runtime_server`: optional RPC surfaces

See [config/README.md](../config/README.md) and `config/default.yaml` for example shapes.
