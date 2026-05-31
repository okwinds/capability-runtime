<div align="center">

[English](02-config-reference.md) | [中文](02-config-reference.zh-CN.md)

</div>

# Config Reference

The public config object is `RuntimeConfig`.

Core fields:

- `mode`: `mock`, `bridge`, or `sdk_native`
- `workspace_root`: root for WAL and runtime state
- `sdk_config_paths`: paths to `skills-runtime-sdk` overlays
- `custom_tools`: host-registered tools injected at runtime
- `preflight_mode`: `error`, `warn`, or `off`
- `sdk_backend`: optional backend injection for offline testing
- `workflow_engine`: optional workflow-engine injection
- `runtime_client` / `runtime_server`: optional RPC surfaces
- `requester_strategy`: `chat_completions` or `responses`; default is
  `chat_completions`
- `max_dynamic_nodes`: hard limit for Dynamic DAG preview compilation/execution

See [config/README.md](../config/README.md) and `config/default.yaml` for example shapes.

Compatibility rule: omitting `requester_strategy` keeps legacy bridge behavior.
Responses mode is opt-in and must not be documented or configured as the default.
`RuntimeConfig.agently_requester` is still accepted as a legacy alias, but new
downstream code should use the neutral `requester_strategy` field.

## Provider And Model Priority

`RuntimeConfig.requester_strategy` chooses the Agently transport lane:

- `chat_completions` builds `OpenAICompatible`.
- `responses` builds `OpenAIResponsesCompatible`.
- `sdk_backend` injection bypasses both lanes and is the right choice for
  deterministic offline tests.

Model priority is independent from transport selection:

1. `AgentSpec.llm_config["model"]` is the stable application entrypoint.
2. The SDK receives that value as `ChatRequest.model`.
3. Provider-returned usage `model` wins when present.
4. If provider usage omits `model`, runtime usage evidence falls back to
   `ChatRequest.model`.

Agently settings should contain transport details such as `base_url`, `auth`,
headers, timeout, and requester plugin configuration. Do not rely on Agently
settings alone to set the runtime request model.
