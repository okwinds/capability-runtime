<div align="center">

[English](06-troubleshooting.md) | [中文](06-troubleshooting.zh-CN.md)

</div>

# 排障指南

- `Capability not found`
  - 能力没有注册，或者 `Runtime.validate()` 仍报告依赖缺失。
- preflight 失败
  - 检查 `sdk_config_paths`、`skills_config` 与当前 mode。
- `NodeReport` 缺失
  - `mock` 模式的证据深度可能低于 `bridge` / `sdk_native`。
- `INVALID_PROMPT_MESSAGES`
  - 使用 `precomposed_messages` 时，检查 `_runtime_prompt.messages`。
  - 多模态输入的 `content` 必须是字符串，或非空的受支持 content parts 列表。
  - v1 只支持 `text` 与 `image_url` parts。未知字段、未知 part type、非法
    `image_url.detail`、空 URL、非有限数字、非 JSON-compatible message 值都会 fail-fast。
- 等待审批
  - 从 `HostRunSnapshot` 或 `NodeReport` 读取 approval key 与工具元数据。
- 怀疑文档漂移
  - 以 `src/capability_runtime/__init__.py` 和包内测试作为公开契约真相源。
