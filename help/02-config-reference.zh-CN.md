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

## Provider 与模型优先级

`RuntimeConfig.requester_strategy` 只选择 Agently transport 通道：

- `chat_completions` 构造 `OpenAICompatible`。
- `responses` 构造 `OpenAIResponsesCompatible`。
- `sdk_backend` 注入会绕过这两条通道，是确定性离线测试的优先入口。

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
