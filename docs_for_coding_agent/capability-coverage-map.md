<div align="center">

[English](capability-coverage-map.md) | [中文](capability-coverage-map.zh-CN.md)

</div>

# Capability Coverage Map

This map ties each public capability area to its documentation entrypoint,
implementation file, runnable example, and regression anchor so documentation
drift is easier to detect.

| Capability Area | Public Entry | Primary Source | Example | Regression Anchor |
|---|---|---|---|---|
| Runtime register / validate / run | `README.md` / `help/03-python-api.md` | `src/capability_runtime/runtime.py` | `examples/01_quickstart/` | `tests/test_public_api_exports.py` |
| Workflow orchestration | `examples/README.md` | `src/capability_runtime/adapters/triggerflow_workflow_engine.py` | `examples/02_workflow/` | `tests/test_examples_smoke.py` |
| NodeReport evidence | `help/05-hosted-runtime-and-evidence.md` | `src/capability_runtime/reporting/node_report.py` | `docs_for_coding_agent/examples/atomic/02_read_node_report/` | `tests/test_coding_agent_examples_atomic.py` |
| Host wait/resume surface | `help/05-hosted-runtime-and-evidence.md` | `src/capability_runtime/host_protocol.py` | `examples/apps/ui_events_showcase/` | `tests/test_runtime_hitl_host_protocol.py` |
| Runtime service facade | `help/05-hosted-runtime-and-evidence.md` | `src/capability_runtime/service_facade.py` | `examples/apps/sse_gateway_minimal/` | `tests/test_runtime_service_session_bridge.py` |
| Coding-agent examples | `docs_for_coding_agent/README.md` | `docs_for_coding_agent/examples/**` | `docs_for_coding_agent/examples/` | `tests/test_coding_agent_examples_atomic.py`, `tests/test_coding_agent_examples_recipes.py` |

## Version Alignment Notes

- the pinned `skills-runtime-sdk` version lives in `pyproject.toml`
- avoid hardcoding stale version text in docs
- when a pinned version must be written, keep it aligned with `pyproject.toml`
