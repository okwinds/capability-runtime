<div align="center">

[English](README.md) | [中文](README.zh-CN.md)

</div>

# capability-runtime

`capability-runtime` 是一个面向生产的运行时/适配层。它通过稳定的 `Runtime`
公共接口，把两条上游能力组合起来：

- `skills-runtime-sdk`：负责 skills、tools、approvals、WAL 与事件证据链
- `Agently`：负责 OpenAI-compatible 传输，以及基于 TriggerFlow 的编排内部实现

本仓公开承诺的契约面刻意收窄为：

- 能力原语：`AgentSpec` 与 `WorkflowSpec`
- 执行入口：`Runtime`
- 证据面：`NodeReport`、宿主快照与 service façade 辅助对象

## 你会得到什么

- 统一执行入口：`Runtime.run()` 与 `Runtime.run_stream()`
- 面向公开 API 的能力注册与 manifest descriptor
- 基于运行时的 Workflow 编排，而不是把 TriggerFlow 暴露成公共 API
- 以 `NodeReport`、工具调用摘要、审批摘要、WAL locator 为核心的证据链
- 面向宿主的等待摘要、approval ticket、resume intent preview、continuity 与 streaming 辅助面
- 通过同一运行时契约承载 runtime capability preview：Responses requester
  显式 opt-in、Dynamic DAG preview、workflow lifecycle 摘要、
  Workspace/Recall context pack、Action artifact evidence 摘要

## 架构总览

```text
                           +-----------------------------+
                           | 宿主应用                     |
                           | - 注册能力                   |
                           | - run / stream / summarize  |
                           +--------------+--------------+
                                          |
                                          v
+------------------------------------------------------------------------+
| capability-runtime                                                     |
|                                                                        |
|  公共契约                                                              |
|  - AgentSpec / WorkflowSpec                                            |
|  - Runtime                                                             |
|  - NodeReport / HostRunSnapshot / RuntimeServiceFacade                 |
|                                                                        |
|  内部适配层                                                            |
|  - AgentAdapter                                                        |
|  - TriggerFlowWorkflowEngine                                           |
|  - service/session continuity bridge                                   |
+------------------------------+-----------------------------------------+
                               |
                               v
                 +-------------------------------+
                 | skills-runtime-sdk            |
                 | - skills + tools              |
                 | - approvals + exec sessions   |
                 | - WAL / AgentEvent evidence   |
                 +---------------+---------------+
                                 |
                                 v
                 +-------------------------------+
                 | Agently / TriggerFlow         |
                 | - OpenAI-compatible transport |
                 | - workflow execution internals|
                 +-------------------------------+
```

## 安装

从源码安装：

```bash
python -m pip install -e .
```

安装开发依赖：

```bash
python -m pip install -e ".[dev]"
```

发布到 PyPI 后，安装方式为：

```bash
python -m pip install capability-runtime
```

导入名：

```python
import capability_runtime
```

## 快速开始

### 1. 离线最小闭环

```bash
python examples/01_quickstart/run_mock.py
```

这条路径覆盖最短闭环：

- 注册 `AgentSpec`
- 校验 registry
- 在 `mode="mock"` 下运行
- 查看终态 `CapabilityResult`

### 2. Bridge 模式连接真实模型

```bash
cp examples/01_quickstart/.env.example examples/01_quickstart/.env
python examples/01_quickstart/run_bridge.py
```

Bridge 模式复用 Agently 的 OpenAI-compatible 传输层，但 skills/tools/WAL
的真实执行语义仍来自 `skills-runtime-sdk`。legacy requester strategy 是
`chat_completions`。Responses mode 必须通过
`RuntimeConfig.requester_strategy="responses"` 显式 opt-in；它不是默认值。

真实 provider 接线顺序：

1. 先通过 gateway 或 `/models` 表面确认模型名可用。
2. 用 `build_openai_provider_requester_factory(...)` 从中立 transport settings
   构造 provider requester factory。
3. chat/completions 保持默认 `requester_strategy="chat_completions"`。
4. 仅当 provider 支持 `/responses` 时，再显式 opt-in responses 通道。
5. 运行 runtime chat 路径：
   `RuntimeConfig(mode="bridge", requester_strategy="chat_completions")`。
6. 运行 runtime responses 路径：
   `RuntimeConfig(mode="bridge", requester_strategy="responses")`。

模型路由是另一条优先级链：`AgentSpec.llm_config["model"]` 会覆写 SDK
`ChatRequest.model`；当 provider usage payload 没有返回 `model` 时，这个
request model 是 runtime bridge 的真相来源。Agently settings 只负责
base URL、auth、requester plugin 等 transport 配置，不能替代
`AgentSpec.llm_config.model`。

### 3. Workflow 编排

```bash
python examples/02_workflow/run.py
```

### 4. Runtime capability preview

```bash
python examples/05_dynamic_dag_preview/run.py
python examples/06_responses_bridge/run.py
```

这些预览能力仍只依赖 `capability_runtime` 公共契约：Dynamic DAG 使用
`DynamicWorkflowPlan` / runtime 方法，Responses 使用
`RuntimeConfig.requester_strategy`。下游不要把 upstream-native `TaskDAG`、
`DynamicTask`、`Workspace`、`Action` 或 requester 对象作为稳定依赖面。

更高层的示例索引请从 [examples/README.md](examples/README.md) 开始。

## 公共 API 一览

包根公开导出的是受支持的契约面：

```python
from capability_runtime import (
    Runtime,
    RuntimeConfig,
    CustomTool,
    ProviderRequester,
    ProviderRequesterFactory,
    ProviderRequesterStrategy,
    build_openai_provider_requester_factory,
    AgentSpec,
    AgentIOSchema,
    WorkflowSpec,
    Step,
    LoopStep,
    ParallelStep,
    ConditionalStep,
    InputMapping,
    CapabilitySpec,
    CapabilityKind,
    CapabilityResult,
    CapabilityStatus,
    DynamicWorkflowNode,
    DynamicWorkflowPlan,
    NodeReport,
    StructuredStreamEvent,
    HostRunSnapshot,
    HostRunStatus,
    ApprovalTicket,
    ResumeIntent,
    RuntimeContextRecordRef,
    RuntimeRecallBackend,
    RuntimeRecallContextPack,
    build_recall_context_pack,
    write_node_report_summary,
    RuntimeServiceFacade,
    RuntimeServiceRequest,
    RuntimeServiceHandle,
    RuntimeSession,
)
```

`RuntimeConfig.mode` 目前支持三种执行模式：

- `mock`：不依赖真实 LLM 的确定性本地测试
- `bridge`：Agently 传输层 + `skills-runtime-sdk` 执行语义
- `sdk_native`：不经过 Agently，直接使用 `skills-runtime-sdk` backend

Provider bridge strategy 与 `mode` 分离：

- `RuntimeConfig.requester_strategy="chat_completions"`：legacy 兼容的默认 bridge 路径。
- `RuntimeConfig.requester_strategy="responses"`：显式 opt-in 的 Responses bridge 路径。
- `sdk_backend` 注入优先于这两种 strategy，用于离线回归和 fake-backend 测试。

Dynamic DAG preview 不会隐式扩展 `WorkflowSpec.steps`：先把 TaskDAG-like
mapping 编译为本仓 `DynamicWorkflowPlan`，用有限 `max_dynamic_nodes` 约束规模，
并且每个节点只通过已注册 capability 执行。

真实 provider 审计证据应落在 `NodeReport.usage`：provider 返回时必须保留
`model`、`request_id`、`provider` 与 token 计数。若 provider 没有返回
`model`，则回退到 `ChatRequest.model`；当已有更可信的 request/provider
模型时，不能把 SDK 占位默认值（例如 `gpt-4`）当作真实 provider 证据。

## 仓库结构

```text
.
├── src/capability_runtime/      # 包源码
├── examples/                    # 面向人类的可运行示例
├── docs_for_coding_agent/       # 编码智能体速读包
├── help/                        # 公开帮助与操作指南
├── config/                      # 配置形态示例
├── scripts/                     # 发布 / 校验辅助脚本
└── tests/                       # 离线回归护栏
```

## 文档导航

- [help/README.md](help/README.md)：公开帮助索引
- [examples/README.md](examples/README.md)：示例导航
- [docs_for_coding_agent/README.md](docs_for_coding_agent/README.md)：编码智能体教学包
- [config/README.md](config/README.md)：配置形态说明

推荐阅读顺序：

1. [help/00-overview.md](help/00-overview.md)
2. [help/01-quickstart.md](help/01-quickstart.md)
3. [help/03-python-api.md](help/03-python-api.md)
4. [examples/README.md](examples/README.md)

## Release 与 PyPI 发布

仓库内置了 GitHub Actions 工作流，用于：

- push / pull request 的 Tier-0 CI
- 基于 tag 或手动触发的 PyPI 发布

发布护栏包括：

- Git tag 必须与 `pyproject.toml` 中的 `[project].version` 一致
- Git tag 必须与 `capability_runtime.__version__` 一致
- 发布前必须先构建 sdist 与 wheel

发布工作流采用 PyPI Trusted Publishing 设计；但仍需要你在 `pypi.org`
后台配置对应的 Trusted Publisher。

## 与上游的关系

- `skills-runtime-sdk` 仍是 skills、approvals、tools、WAL 与事件证据链的真相源。
- Agently `SkillsExecutor` 不是 `capability-runtime` 的 skills 驱动器。它的
  编写范式可以作为 `SKILL.md` bundle 设计参考，但 skill 注入、tool 执行、
  approval、WAL、events 与 `NodeReport` 聚合仍由 `skills-runtime-sdk` 负责。
- `Agently` 仍是本仓选择桥接而非 fork/重造的传输与编排底座。
- `capability-runtime` 的职责是把这些上游能力收敛成更小、更稳定的宿主侧运行时契约面。
- Legacy mode 非破坏：不配置 Responses、Dynamic DAG、Workspace/Recall 或
  Action artifact evidence 预览能力时，既有 `Runtime.run()` /
  `Runtime.run_stream()` / `WorkflowSpec` 消费方仍可继续读取原有
  `NodeReport` 与 UI event 字段。
