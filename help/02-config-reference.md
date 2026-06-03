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
- `provider_requester_factory`: preferred bridge transport injection. It accepts
  a runtime-owned `ProviderRequesterFactory` and does not require downstream
  code to pass a provider-native agent object into `RuntimeConfig`
- `requester_strategy`: `chat_completions` or `responses`; default is
  `chat_completions`
- `tool_choice_after_tool_result`: optional bridge compatibility override for
  follow-up LLM turns after a tool result; allowed values are `none` or `auto`
- `max_dynamic_nodes`: hard limit for Dynamic DAG preview compilation/execution

See [config/README.md](../config/README.md) and `config/default.yaml` for example shapes.

Compatibility rule: omitting `requester_strategy` keeps legacy bridge behavior.
Responses mode is opt-in and must not be documented or configured as the default.
`RuntimeConfig.agently_requester` is still accepted as a legacy alias, but new
downstream code should use the neutral `requester_strategy` field.
`RuntimeConfig.agently_agent` is a legacy compatibility path. New bridge
integrations should pass `provider_requester_factory` and keep provider-native
objects inside bootstrap/adapter code.
For regular OpenAI-compatible bootstrap code, use
`build_openai_provider_requester_factory(base_url=..., transport_model=..., api_key=..., strategy=...)`.
The helper rejects plain `http://` by default. For a controlled private provider
that cannot use HTTPS, pass `allow_insecure_transport=True` explicitly or set
`CAPRT_REAL_PROVIDER_ALLOW_INSECURE_TRANSPORT=1`; release gates should also
restrict trusted hosts.
Hosts with a provider-native agent should wrap it behind their own
`ProviderRequesterFactory`; do not import adapter-internal helpers from
application code.

## Provider And Model Priority

`RuntimeConfig.requester_strategy` chooses the runtime transport lane:

- `chat_completions` keeps the default chat/completions lane.
- `responses` opts in to the responses lane.
- `sdk_backend` injection bypasses both lanes and is the right choice for
  deterministic offline tests.
- `provider_requester_factory` is the stable bridge injection point when a host
  wants to provide a transport requester without exposing provider-native agent
  objects through public application code.
- `build_openai_provider_requester_factory(...)` is the recommended helper for
  OpenAI-compatible real provider wiring; it constructs the runtime-owned
  requester factory from neutral transport settings.
- The helper defaults to HTTPS-only transport. Private `http://` providers must
  opt in explicitly with `allow_insecure_transport=True` or
  `CAPRT_REAL_PROVIDER_ALLOW_INSECURE_TRANSPORT=1`.
- `transport_model` is only the provider requester bootstrap fallback. The
  runtime request model still comes from `AgentSpec.llm_config["model"]` / the
  SDK `ChatRequest.model`.

Model priority is independent from transport selection:

1. `AgentSpec.llm_config["model"]` is the stable application entrypoint.
2. The SDK receives that value as `ChatRequest.model`.
3. Provider-returned usage `model` wins when present.
4. If provider usage omits `model`, runtime usage evidence falls back to
   `ChatRequest.model`.

Agently settings should contain transport details such as `base_url`, `auth`,
headers, timeout, and requester plugin configuration. Do not rely on Agently
settings alone to set the runtime request model.

`AgentSpec.llm_config["tool_choice"]` is passed through by default. If a specific
provider repeatedly calls the same tool after a forced first tool call, set
`RuntimeConfig.tool_choice_after_tool_result="none"` explicitly for that runtime.
Do not rely on the runtime to silently reinterpret provider `tool_choice`
semantics.
