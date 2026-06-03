<div align="center">

[English](03-python-api.md) | [中文](03-python-api.zh-CN.md)

</div>

# Python API

受支持的公共 API 以包根导入面为准。

## 核心对象

- `Runtime`
- `RuntimeConfig`
- `CustomTool`

Provider bridge 新增面：

- `ProviderRequesterStrategy`：`"chat_completions"` 或 `"responses"`。
- `ToolChoiceAfterToolResult`：工具结果回注后的显式 provider 兼容覆写，
  当前为 `"none"` 或 `"auto"`。
- `RuntimeConfig.requester_strategy`：requester strategy，默认
  `"chat_completions"`，用于 legacy 兼容。
- `RuntimeConfig.max_dynamic_nodes`：Dynamic DAG preview 硬上限。
- `RuntimeRecallBackend`：本仓 runtime-owned context recall backend 协议。
- `build_recall_context_pack` / `write_node_report_summary`：从根包导出的中立
  recall context helper。

requester selection 不负责选择业务模型。runtime 模型应通过
`AgentSpec.llm_config["model"]` 设置；lifecycle 层会把它复制到 SDK
`ChatRequest.model`，再由 provider backend 发出 wire request。Agently settings
仍只是 transport 设置。

## 能力协议

- `CapabilitySpec`
- `CapabilityKind`
- `CapabilityResult`
- `CapabilityStatus`
- `AgentSpec`
- `AgentIOSchema`
- `PromptRenderMode`
- `WorkflowSpec`
- `DynamicWorkflowNode`
- `DynamicWorkflowPlan`
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

### 多模态 Precomposed Messages

`precomposed_messages` 也可以承载 OpenAI-compatible 的多模态 content
parts。这是宿主显式控制的边界：runtime 负责校验、摘要和透传 messages，但不负责下载、
转码、OCR、ASR、视频抽帧或媒体生命周期管理。

支持的 `content` 形态：

- `str`：既有纯文本 message content。
- `list[dict]`：v1 stable content parts。

v1 支持的 content parts：

```python
messages = [
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "Compare these images."},
            {
                "type": "image_url",
                "image_url": {
                    "url": "https://example.test/a.png",
                    "detail": "auto",
                },
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": "https://example.test/b.png",
                },
            },
        ],
    }
]
```

规则与限制：

- `text.text` 必须是字符串。空字符串允许透传。
- `image_url.url` 必须是非空字符串。runtime 不下载，也不校验 URL 可达性。
- `image_url.detail` 如存在，必须是 `auto`、`low` 或 `high`。
- 允许多个 `image_url` parts；只包含图片 part 的 content list 也合法。
- 空 content part list、未知 part type、未知字段、非有限数字、非 JSON-compatible
  message 值都会 fail-fast 为 `INVALID_PROMPT_MESSAGES`。
- `input_audio`、`file`、`video` 等预留或 provider-specific parts 不属于 v1
  接受范围。需要支持时应通过后续显式契约扩展，而不是依赖静默 passthrough。

证据侧，`NodeReport.meta` 只记录最小摘要：

- `prompt_modalities`
- `prompt_content_part_counts`
- `prompt_media_count`

它不会记录完整 `messages[]`、完整 URL、base64 载荷、媒体内容、prompt 明文、
`tool_calls`、`tool_call_id` 或其他 provider extra fields。Runtime UI events 也不投影这些
prompt 摘要字段。

多模态输出继续使用既有 artifact locator：

- `CapabilityResult.artifacts: list[str]`
- `NodeReport.artifacts: list[str]`

runtime 不为图片、音频、视频或文件新增并行二进制输出字段。

`NodeReport.meta` 会记录 `prompt_render_mode`、`prompt_profile`、`prompt_hash`、消息数量、角色列表和 composer 版本等 prompt evidence 摘要；不会记录完整 prompt 明文或完整 `messages[]` 载荷。

## 证据与宿主表面

- `NodeReport`
- `ApprovalTicket`
- `ResumeIntent`
- `HostRunSnapshot`
- `WorkflowRunSnapshot` lifecycle 字段为 additive。消费方可在字段存在时读取
  `lifecycle_state`、`execution_id`、`state_version`、`intervention_mode`、
  `pending_interventions`、`close_reason`；旧事件消费方可以忽略这些字段。
- `RuntimeServiceFacade`
- `RuntimeServiceRequest`
- `RuntimeServiceHandle`
- `RuntimeSession`

## Runtime Capability Preview

Responses bridge：

```python
from capability_runtime import RuntimeConfig

cfg = RuntimeConfig(mode="bridge", requester_strategy="responses")
```

`"responses"` 是 opt-in。默认仍是 `"chat_completions"`；离线测试注入
`sdk_backend` 时仍优先绕过真实 requester。

真实 provider 审计：

- 用 `build_openai_provider_requester_factory(...)` 构造 bridge transport，
  并通过 `RuntimeConfig.requester_strategy` 选择通道。
- `NodeReport.usage.model` 优先采用 provider usage `model`，否则回退到
  `ChatRequest.model`。
- provider/gateway 返回时，`NodeReport.usage.request_id` 与
  `NodeReport.usage.provider` 必须保留。
- Agently settings 只配置 transport；不要把它当作唯一模型配置入口。

Dynamic DAG preview：

```python
plan = runtime.compile_dynamic_workflow_plan(task_dag_like_mapping)
result = await runtime.run_dynamic_workflow(plan, input={"topic": "release"})
```

TaskDAG-like 数据必须先编译为本仓 `DynamicWorkflowPlan`；不要把 upstream-native
`TaskDAG` / `DynamicTask` 对象作为下游应用稳定契约透传。节点只通过已注册
capability id 执行，并通过有限 `max_dynamic_nodes` 与 `DYNAMIC_DAG_*` 诊断
fail-closed。

Recall context preview 接受本仓中立 `RuntimeRecallBackend`，并暴露
`RuntimeRecallContextPack`；它不是 WAL 或 NodeReport 的替代品。上游
Workspace 可以在 backend 协议背后被适配，但下游不应依赖上游原生对象。
Action artifact evidence 只暴露脱敏 artifact reference 与 `NodeReport.meta`
摘要，不读取 artifact 原文。

Agently `SkillsExecutor` 不是 `capability-runtime` 的 skills 驱动器。可以复用
它的一般 `SKILL.md` 编写纪律，但 `AgentSpec.skills` 仍通过
`skills-runtime-sdk` 完成 skill 注入、tools、approval、WAL、events 与
`NodeReport` 证据链。

## 错误类型

- `RuntimeFrameworkError`
- `CapabilityNotFoundError`
