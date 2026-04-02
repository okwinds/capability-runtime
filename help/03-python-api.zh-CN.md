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
- `WorkflowSpec`
- `Step`
- `LoopStep`
- `ParallelStep`
- `ConditionalStep`
- `InputMapping`

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
