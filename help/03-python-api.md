<div align="center">

[English](03-python-api.md) | [中文](03-python-api.zh-CN.md)

</div>

# Python API

The supported public API is the package root import surface.

## Core

- `Runtime`
- `RuntimeConfig`
- `CustomTool`

## Capability Protocol

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

## Evidence And Host Surfaces

- `NodeReport`
- `ApprovalTicket`
- `ResumeIntent`
- `HostRunSnapshot`
- `RuntimeServiceFacade`
- `RuntimeServiceRequest`
- `RuntimeServiceHandle`
- `RuntimeSession`

## Errors

- `RuntimeFrameworkError`
- `CapabilityNotFoundError`
