<div align="center">

[English](02-config-reference.md) | [中文](02-config-reference.zh-CN.md)

</div>

# 配置参考

公开配置对象是 `RuntimeConfig`。

核心字段：

- `mode`：`mock`、`bridge`、`sdk_native`
- `workspace_root`：WAL 与运行态目录根路径
- `sdk_config_paths`：`skills-runtime-sdk` overlay 路径
- `custom_tools`：宿主注入的自定义工具
- `preflight_mode`：`error`、`warn`、`off`
- `sdk_backend`：离线测试用 backend 注入
- `workflow_engine`：可选 workflow engine 注入
- `runtime_client` / `runtime_server`：可选 RPC 表面

示例形态见 [config/README.md](../config/README.md) 与 `config/default.yaml`。
