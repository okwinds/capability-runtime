<div align="center">

[English](01-quickstart.md) | [中文](01-quickstart.zh-CN.md)

</div>

# Quickstart

## Install

```bash
python -m pip install -e ".[dev]"
```

## Smallest Offline Loop

```bash
python examples/01_quickstart/run_mock.py
```

## Bridge Mode

```bash
cp examples/01_quickstart/.env.example examples/01_quickstart/.env
python examples/01_quickstart/run_bridge.py
```

Bridge mode keeps the public entrypoint at `Runtime`. The default bridge
requester remains `chat_completions`; opt in to Responses with
`RuntimeConfig.requester_strategy="responses"` only when the runtime and provider
configuration are ready for the `/responses` path.

Use this order for real provider smoke tests:

1. `models`: confirm the configured `MODEL_NAME` exists for the gateway.
2. `transport`: build `provider_requester_factory` with
   `build_openai_provider_requester_factory(...)`.
3. `chat`: run bridge mode with the default `chat_completions` requester.
4. `responses`: opt in only when the gateway supports `/responses`.
5. `runtime responses`: run bridge mode with
   `RuntimeConfig.requester_strategy="responses"`.

Set the runtime request model through `AgentSpec.llm_config={"model": ...}`.
That value becomes the SDK `ChatRequest.model`; Agently settings are transport
settings and are not a substitute for the runtime model override.

## Workflow Example

```bash
python examples/02_workflow/run.py
```

## Runtime Capability Preview Examples

```bash
python examples/05_dynamic_dag_preview/run.py
python examples/06_responses_bridge/run.py
```

Use these examples as capability-runtime previews. They should not be treated as
permission to import upstream-native workflow, requester, Workspace, or Action
objects in downstream application code.

After a real bridge run, inspect `result.node_report.usage`. For auditability it
should preserve `model`, `request_id`, `provider`, and token counts when the
provider or gateway returns them.
