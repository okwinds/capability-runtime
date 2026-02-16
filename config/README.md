# 配置示例（config/）

本目录提供 `agently-skills-runtime` 的**示例配置**，用于帮助你复刻运行环境与集成形态。

重要说明：
- 本仓库是桥接层（Bridge），**主配置以 SDK overlays 为准**。
- 生产推荐：把 secrets（API key / DSN）挂载到镜像外部，由部署系统注入 OS env。
- 示例只表达“形态”，不绑定任何具体业务。

## 文件说明

- `config/default.yaml`
  - bridge 层示例配置（workspace_root / overlays / preflight / backend_mode / upstream 校验）。
  - 对应 `agently_skills_runtime.config.BridgeConfigModel` 与 `AgentlySkillsRuntimeConfig`。
- `config/sdk.example.yaml`
  - SDK overlays 示例（Strict Catalog：spaces + sources + scan/injection）。
  - 以 `skills-runtime-sdk-python`（模块 `agent_sdk`）的配置 schema 为准。

## 关键概念

- `backend_mode`：
  - `agently_openai_compatible`（默认）：复用 Agently builtins 的 OpenAICompatible requester。
  - `sdk_openai_chat_completions`：显式使用 SDK 原生 OpenAI-compatible backend。

- `upstream_verification_mode`：
  - `off`：不校验上游来源。
  - `warn`：发现不匹配仅记录到 `NodeReport.meta`。
  - `strict`：发现不匹配直接 fail-closed（建议生产使用）。

- `agently_fork_root` / `skills_runtime_sdk_fork_root`：
  - 期望 fork 根目录；用于校验当前导入模块是否来自指定 fork。
