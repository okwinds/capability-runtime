<div align="center">

[English](00-overview.md) | [中文](00-overview.zh-CN.md)

</div>

# 总览

`capability-runtime` 的职责，是把更大的上游工具链收敛成更小的宿主侧 API：

- 用 `AgentSpec` 和 `WorkflowSpec` 声明能力
- 在 `Runtime` 中注册并校验
- 执行后从 `CapabilityResult.node_report` 读取终态证据

适用场景：

- 你需要更小、更稳定的宿主运行时契约
- 你希望能力编排可测试、可回归
- 你要把 tools / approvals / WAL 以证据优先的方式接入业务侧
