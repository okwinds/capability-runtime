<div align="center">

[English](05-hosted-runtime-and-evidence.md) | [中文](05-hosted-runtime-and-evidence.zh-CN.md)

</div>

# 宿主运行时与证据链

当宿主应用不只需要终态 `output` 时，请使用这些表面。

## 证据链

- `NodeReport`：聚合后的终态结构化证据
- `events_path`：尽力指向 WAL events 的定位符
- tool-call summaries：审批、状态、错误类别的聚合摘要

## 宿主协议

- `ApprovalTicket`
- `ResumeIntent`
- `HostRunSnapshot`

这些是 wait/resume 与人工审批流程的稳定宿主对象。

## Service Facade

当宿主需要这些能力时，请使用 `RuntimeServiceFacade`：

- 稳定的 request / handle 模型
- JSONL 或 SSE framing
- 基于 `RuntimeSession` 的 continuity 注入
- 适合 RPC 包装的更小运行时表面
