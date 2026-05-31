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
| Real provider wiring | `help/01-quickstart.md` / `help/02-config-reference.md` | `RuntimeConfig.requester_strategy` + `AgentSpec.llm_config.model` -> SDK `ChatRequest.model` | `examples/01_quickstart/`, `examples/06_responses_bridge/` | `tests/integration/test_runtime_real_provider_bridge.py` |
| Usage model/request/provider audit | `help/03-python-api.md` | `NodeReport.usage` + bridge usage sink | `examples/03_bridge_e2e/`, `examples/06_responses_bridge/` | `tests/test_openai_responses_compatible_bridge.py`, `tests/test_per_capability_llm_config_model_routing.py` |
| Responses bridge opt-in | `help/02-config-reference.md` / `help/03-python-api.md` | `RuntimeConfig.requester_strategy` + Agently bridge adapter | `examples/06_responses_bridge/` | `tests/test_openai_responses_compatible_bridge.py` |
| Dynamic DAG preview | `help/03-python-api.md` | `DynamicWorkflowPlan` + runtime dynamic workflow methods | `examples/05_dynamic_dag_preview/` | `tests/test_dynamic_workflow_plan_contract.py`, `tests/test_dynamic_workflow_runtime.py` |
| Workflow lifecycle preview | `help/03-python-api.md` | `WorkflowRunSnapshot` + UI event projection | `examples/04_triggerflow_orchestration/` | `tests/test_triggerflow_lifecycle_mapping.py` |
| Workspace/Recall preview | `help/03-python-api.md` | Runtime context pack adapter | `examples/08_workspace_recall_preview/` | `tests/test_agently_workspace_recall_preview.py` |
| Action artifact evidence | `help/03-python-api.md` / `help/05-hosted-runtime-and-evidence.md` | `NodeReport.artifacts` / `NodeReport.meta` summaries | `examples/09_action_artifact_evidence/`, `docs_for_coding_agent/examples/recipes/03_skill_exec_actions/` | `tests/test_agently_action_artifact_evidence.py` |

## Version Alignment Notes

- the pinned `skills-runtime-sdk` version lives in `pyproject.toml`
- avoid hardcoding stale version text in docs
- when a pinned version must be written, keep it aligned with `pyproject.toml`
- Responses support is opt-in. Do not describe Responses as the
  default unless a future source spec changes the default explicitly.
- Real provider docs must keep model precedence explicit:
  `AgentSpec.llm_config.model` / `ChatRequest.model` is the runtime model path;
  Agently settings are transport-only.
