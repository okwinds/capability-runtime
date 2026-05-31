<div align="center">

[English](01-quickstart.md) | [中文](01-quickstart.zh-CN.md)

</div>

# 快速开始

## 安装

```bash
python -m pip install -e ".[dev]"
```

## 最小离线闭环

```bash
python examples/01_quickstart/run_mock.py
```

## Bridge 模式

```bash
cp examples/01_quickstart/.env.example examples/01_quickstart/.env
python examples/01_quickstart/run_bridge.py
```

Bridge 模式的公开入口仍是 `Runtime`。默认 bridge requester 仍为
`chat_completions`；只有在 runtime 与 provider 配置都准备好 `/responses`
路径时，才通过 `RuntimeConfig.requester_strategy="responses"` 显式 opt-in。

真实 provider smoke 请按这个顺序执行：

1. `models`：确认 gateway 上配置的 `MODEL_NAME` 存在。
2. `chat`：配置 `OpenAICompatible` provider 通道，跑 chat/completions。
3. `responses`：只有 gateway 支持 `/responses` 时，才配置 Agently
   `OpenAIResponsesCompatible` provider 通道。
4. `runtime chat`：用默认 `chat_completions` requester 跑 bridge mode。
5. `runtime responses`：用
   `RuntimeConfig.requester_strategy="responses"` 跑 bridge mode。

runtime 请求模型应通过 `AgentSpec.llm_config={"model": ...}` 设置。该值会成为
SDK `ChatRequest.model`；Agently settings 是 transport 配置，不能替代 runtime
模型覆写。

## Workflow 示例

```bash
python examples/02_workflow/run.py
```

## Runtime Capability Preview 示例

```bash
python examples/05_dynamic_dag_preview/run.py
python examples/06_responses_bridge/run.py
```

这些示例是 capability-runtime 预览能力入口。不要据此在下游应用代码中直接
import upstream-native workflow、requester、Workspace 或 Action 对象。

真实 bridge 运行后检查 `result.node_report.usage`。为了可审计，provider 或
gateway 返回时应保留 `model`、`request_id`、`provider` 与 token 计数。
