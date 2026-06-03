<div align="center">

[English](05-hosted-runtime-and-evidence.md) | [中文](05-hosted-runtime-and-evidence.zh-CN.md)

</div>

# 宿主运行时与证据链

当宿主应用不只需要终态 `output` 时，请使用这些表面。

## 证据链

- `NodeReport`：聚合后的终态结构化证据
- `events_path`：尽力指向 WAL events 的定位符
- tool-call summaries：审批、状态、错误类别的聚合摘要

对于多模态 `precomposed_messages`，`NodeReport.meta` 只记录安全的 prompt
摘要：

- `prompt_modalities`
- `prompt_content_part_counts`
- `prompt_media_count`

它不会记录完整 `messages[]`、URL、base64 载荷、媒体字节、prompt 明文、
`tool_calls` 或 `tool_call_id`。Runtime UI events 仍然只是投影事件，不是审计真相源，
也不会投影这些多模态 prompt 摘要字段。

媒体或文件输出继续表示为 artifact locator：

- `CapabilityResult.artifacts`
- `NodeReport.artifacts`

不要把 UI event evidence 当成完整 artifact 真相源。稳定证据面是终态结果与
`NodeReport`。

## 宿主协议

- `ApprovalTicket`
- `ResumeIntent`
- `HostRunSnapshot`

这些是等待摘要、approval ticket 与 resume intent preview 的稳定宿主对象。
本版本没有把 `Runtime.continue_run()` / `Runtime.describe_wait()` 作为公开
Runtime API 交付；宿主应使用当前 summary / ticket / intent 辅助对象，不要假设
已经具备基于 snapshot 的恢复执行能力。

## Service Facade

当宿主需要这些能力时，请使用 `RuntimeServiceFacade`：

- 稳定的 request / handle 模型
- JSONL 或 SSE framing
- 基于 `RuntimeSession` 的 continuity 注入
- 适合 RPC 包装的更小运行时表面
