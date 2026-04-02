<div align="center">

[English](capability-coverage-map.md) | [中文](capability-coverage-map.zh-CN.md)

</div>

# 能力覆盖矩阵

把“能力点”与“公开入口、示例、测试、证据断言”对应起来，避免文档和实现继续漂移。

| 能力点 | 公开入口 | 主要源码 | 示例 | 回归入口 |
|---|---|---|---|---|
| Runtime register / validate / run | `README.md` / `help/03-python-api.md` | `src/capability_runtime/runtime.py` | `examples/01_quickstart/` | `tests/test_public_api_exports.py` |
| Workflow orchestration | `examples/README.md` | `src/capability_runtime/adapters/triggerflow_workflow_engine.py` | `examples/02_workflow/` | `tests/test_examples_smoke.py` |
| NodeReport evidence | `help/05-hosted-runtime-and-evidence.md` | `src/capability_runtime/reporting/node_report.py` | `docs_for_coding_agent/examples/atomic/02_read_node_report/` | `tests/test_coding_agent_examples_atomic.py` |
| Host wait/resume surface | `help/05-hosted-runtime-and-evidence.md` | `src/capability_runtime/host_protocol.py` | `examples/apps/ui_events_showcase/` | `tests/test_runtime_hitl_host_protocol.py` |
| Runtime service facade | `help/05-hosted-runtime-and-evidence.md` | `src/capability_runtime/service_facade.py` | `examples/apps/sse_gateway_minimal/` | `tests/test_runtime_service_session_bridge.py` |
| Coding-agent examples | `docs_for_coding_agent/README.md` | `docs_for_coding_agent/examples/**` | `docs_for_coding_agent/examples/` | `tests/test_coding_agent_examples_atomic.py`, `tests/test_coding_agent_examples_recipes.py` |

## 版本对齐提醒

- `skills-runtime-sdk` 的 pinned 版本以 `pyproject.toml` 为准。
- 文档不要再手写过期的版本号；确实需要写 pin 时，必须和 `pyproject.toml` 一致。
