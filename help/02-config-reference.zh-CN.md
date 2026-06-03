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
- `provider_requester_factory`：首选 bridge transport 注入入口。它接收本仓
  `ProviderRequesterFactory`，下游业务代码不需要把 provider 原生 agent 对象传入
  `RuntimeConfig`
- `requester_strategy`：`chat_completions` 或 `responses`；默认是
  `chat_completions`
- `tool_choice_after_tool_result`：可选 bridge 兼容覆写；当工具结果已回注后的后续
  LLM turn 需要改写 `tool_choice` 时，可显式设为 `none` 或 `auto`
- `max_dynamic_nodes`：Dynamic DAG preview 编译/执行硬上限

示例形态见 [config/README.md](../config/README.md) 与 `config/default.yaml`。

兼容规则：省略 `requester_strategy` 时保持 legacy bridge 行为。Responses mode
是 opt-in，不得在文档或配置中描述为默认。
`RuntimeConfig.agently_requester` 仍作为旧调用方兼容别名保留；新下游代码应使用
中立字段 `requester_strategy`。
`RuntimeConfig.agently_agent` 是旧兼容路径。新的 bridge 集成应传入
`provider_requester_factory`，把 provider 原生对象限制在 bootstrap/adapter 代码内。
常规 OpenAI-compatible 接线应使用
`build_openai_provider_requester_factory(base_url=..., transport_model=..., api_key=..., strategy=...)`。
该 helper 默认拒绝明文 `http://`。受控私有 provider 确实无法使用 HTTPS 时，
必须显式传入 `allow_insecure_transport=True`，或设置
`CAPRT_REAL_PROVIDER_ALLOW_INSECURE_TRANSPORT=1`；发布门禁仍应限制受信 host。
已经持有 provider 原生 agent 的宿主，应自行包装成 `ProviderRequesterFactory`；
应用代码不要 import adapter 内部 helper。

## Provider 与模型优先级

`RuntimeConfig.requester_strategy` 只选择 runtime transport 通道：

- `chat_completions` 保持默认 chat/completions 通道。
- `responses` 显式 opt-in responses 通道。
- `sdk_backend` 注入会绕过这两条通道，是确定性离线测试的优先入口。
- 宿主需要提供 transport requester 时，`provider_requester_factory` 是稳定
  bridge 注入入口，不要求公开应用代码持有 provider 原生 agent 对象。
- 常规 OpenAI-compatible 真实 provider 接线推荐
  `build_openai_provider_requester_factory(...)`；它用中立 transport settings
  构造本仓 requester factory。
- helper 默认只允许 HTTPS transport。私有 `http://` provider 必须显式通过
  `allow_insecure_transport=True` 或
  `CAPRT_REAL_PROVIDER_ALLOW_INSECURE_TRANSPORT=1` opt-in。
- `transport_model` 只是 provider requester bootstrap fallback；Runtime 真实请求模型
  仍来自 `AgentSpec.llm_config["model"]` / SDK `ChatRequest.model`。

模型优先级独立于 transport 选择：

1. `AgentSpec.llm_config["model"]` 是稳定的应用入口。
2. SDK 会把这个值作为 `ChatRequest.model`。
3. provider usage 返回 `model` 时，以 provider 返回值为准。
4. provider usage 不返回 `model` 时，runtime usage evidence 回退到
   `ChatRequest.model`。

Agently settings 应只放 `base_url`、`auth`、headers、timeout、requester
plugin 配置等 transport 信息。不要只靠 Agently settings 设置 runtime 请求模型。

默认情况下，`AgentSpec.llm_config["tool_choice"]` 会原样透传。若某个 provider
在强制首轮工具调用后反复调用同一工具，可以为该 runtime 显式设置
`RuntimeConfig.tool_choice_after_tool_result="none"`。不要依赖 runtime 静默改写
provider 的 `tool_choice` 语义。
