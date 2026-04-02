<div align="center">

[English](00-mental-model.md) | [中文](00-mental-model.zh-CN.md)

</div>

# 心智模型：Protocol → Runtime → Report

本仓不是另一个“Prompt 工程项目”，也不是重新发明一套 agent framework。

请用下面三层理解它：

## 1. Protocol

- 声明能力：`AgentSpec` / `WorkflowSpec`
- 定义输入输出与编排关系
- 不承担执行职责

## 2. Runtime

- 统一执行入口：`Runtime.run()` / `Runtime.run_stream()`
- 通过 `RuntimeConfig.mode` 切换 `mock` / `bridge` / `sdk_native`
- 对宿主公开稳定、可回归的运行时表面

## 3. Report

- 终态结果里优先看 `NodeReport`
- `NodeReport` 聚合了 WAL、tool calls、approval、events_path 等结构化证据
- `output` 仍保留，但更适合数据面消费，而不是编排判定

## 上游分工

- `skills-runtime-sdk`：skills、tools、approvals、WAL、events
- `Agently`：OpenAI-compatible transport 与 Workflow 内部编排底座
- `capability-runtime`：把上游能力收敛为更小的宿主契约

## 读代码建议

1. `src/capability_runtime/__init__.py`
2. `src/capability_runtime/runtime.py`
3. `src/capability_runtime/protocol/`
4. `src/capability_runtime/service_facade.py`
5. `src/capability_runtime/reporting/node_report.py`
