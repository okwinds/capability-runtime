<div align="center">

[English](contract.md) | [中文](contract.zh-CN.md)

</div>

# 编码任务契约

当你在本仓做实现时，默认按这个最小流程交付：

1. 先明确规格、范围和禁止项
2. 补或更新测试计划
3. 在 `Runtime` 公共契约内实现最小改动
4. 运行离线回归
5. 同步更新公开文档

## Runtime 契约

- 统一入口：`Runtime.run()` / `Runtime.run_stream()`
- 注册：`Runtime.register()` / `Runtime.register_many()`
- 校验：`Runtime.validate()`

## Workflow 检查点

- `Step.id` 必须唯一
- `InputMapping.source` 必须可解析
- loop 输入必须解析成 list
- 嵌套深度受 `RuntimeConfig.max_depth` 约束

## 绝对不要做的事

- 不要在 protocol 层引入上游执行依赖
- 不要绕过 `Runtime` 手写另一套编排语义
- 不要把业务规则硬写进 runtime 核心
- 不要提交真实 `.env` 或私有协作文档
