<div align="center">

[English](03-python-api.md) | [中文](03-python-api.zh-CN.md)

</div>

# Python API

受支持的公共 API 以包根导入面为准。

## 核心对象

- `Runtime`
- `RuntimeConfig`
- `CustomTool`

## 能力协议

- `CapabilitySpec`
- `CapabilityKind`
- `CapabilityResult`
- `CapabilityStatus`
- `AgentSpec`
- `AgentIOSchema`
- `PromptRenderMode`
- `WorkflowSpec`
- `Step`
- `LoopStep`
- `ParallelStep`
- `ConditionalStep`
- `InputMapping`

## Agent Prompt 渲染

`AgentSpec` 支持面向生产生成任务的 prompt 渲染策略：

- `structured_task`：默认兼容模式。Runtime 会根据 `system_prompt`、能力描述、input、output schema 和 skill mentions 生成 SDK task 文本。
- `direct_task_text`：宿主在 `input["_runtime_prompt"]["task_text"]` 中提供最终 task 文本。
- `precomposed_messages`：宿主在 `input["_runtime_prompt"]["messages"]` 中提供最终 provider messages。

`_runtime_prompt` 是保留的 runtime 控制面，不会作为业务 input 渲染，也不应被应用复用为普通字段名。

示例：

```python
from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec

spec = AgentSpec(
    base=CapabilitySpec(id="writer", kind=CapabilityKind.AGENT, name="Writer"),
    prompt_render_mode="precomposed_messages",
    prompt_profile="generation_direct",
)

result = await runtime.run(
    "writer",
    input={
        "_runtime_prompt": {
            "messages": [
                {"role": "system", "content": "..."},
                {"role": "user", "content": "..."},
            ],
            "trace": {"prompt_hash": "sha256:<64 lowercase hex>"},
        }
    },
)
```

`NodeReport.meta` 会记录 `prompt_render_mode`、`prompt_profile`、`prompt_hash`、消息数量、角色列表和 composer 版本等 prompt evidence 摘要；不会记录完整 prompt 明文或完整 `messages[]` 载荷。

## 证据与宿主表面

- `NodeReport`
- `ApprovalTicket`
- `ResumeIntent`
- `HostRunSnapshot`
- `RuntimeServiceFacade`
- `RuntimeServiceRequest`
- `RuntimeServiceHandle`
- `RuntimeSession`

## 错误类型

- `RuntimeFrameworkError`
- `CapabilityNotFoundError`
