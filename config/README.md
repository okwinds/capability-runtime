<div align="center">

[English](README.md) | [中文](README.zh-CN.md)

</div>

# config/

This directory contains example configuration shapes for `capability-runtime`.

Important boundaries:

- the repository exposes `Runtime` and `RuntimeConfig` as the public entrypoint
- example YAML files describe shapes, not secrets
- runtime-only objects such as approval providers or provider requester
  factories are injected by host code, not by static YAML
- `provider_requester_factory` is the preferred bridge transport injection point;
  `agently_agent` remains a legacy compatibility path and should not be used by
  new application code as the primary bridge surface
- for regular OpenAI-compatible real provider wiring, host bootstrap code should
  build that factory with `build_openai_provider_requester_factory(...)`.
  Hosts that already own a provider-native agent should wrap it behind their own
  `ProviderRequesterFactory`; application code should not import
  adapter-internal helpers.
- `build_openai_provider_requester_factory(...)` rejects plain `http://` by
  default. Controlled private providers must pass
  `allow_insecure_transport=True` or set
  `CAPRT_REAL_PROVIDER_ALLOW_INSECURE_TRANSPORT=1`; release gates should also
  restrict trusted hosts.
- requester strategy is a capability-runtime setting. Keep the default
  `requester_strategy: "chat_completions"` unless the host explicitly opts in to
  Responses.
- model selection is not an Agently settings concern. Set per-capability models
  through `AgentSpec.llm_config["model"]`; runtime copies that value into SDK
  `ChatRequest.model`.

## Files

- `default.yaml`
  - Example shape for `RuntimeConfig`
  - field names must stay aligned with `src/capability_runtime/config.py`
- `sdk.example.yaml`
  - Example overlay for `skills-runtime-sdk`
  - useful for strict catalog, sources, and mention/preflight demonstrations

## Example Usage

```python
from pathlib import Path

import yaml

from capability_runtime import Runtime, RuntimeConfig

raw = yaml.safe_load(Path("config/default.yaml").read_text(encoding="utf-8")) or {}
cfg = RuntimeConfig(
    mode=str(raw.get("mode") or "bridge"),
    workspace_root=Path(str(raw.get("workspace_root") or ".")),
    preflight_mode=str(raw.get("preflight_mode") or "error"),
    requester_strategy=str(raw.get("requester_strategy") or "chat_completions"),
    max_dynamic_nodes=int(raw.get("max_dynamic_nodes") or 64),
)

runtime = Runtime(cfg)
print(runtime.validate())
```

## Notes

- `sdk_config_paths` should point to real overlay files controlled by the host application.
- `preflight_mode="error"` is the safest default when you want fail-closed behavior.
- `requester_strategy="responses"` is opt-in and must not be treated as the
  default bridge mode.
- Existing callers may still pass `RuntimeConfig.agently_requester`; new config
  templates should prefer `requester_strategy`.
- Existing callers may still pass `RuntimeConfig.agently_agent`; new bridge
  bootstrap code should prefer `provider_requester_factory`, usually produced by
  `build_openai_provider_requester_factory(...)`.
- Private `http://` provider wiring is an explicit exception, not a default.
  Prefer HTTPS unless the provider is on a controlled private network and a
  trusted-host guard is also in place.
- `sdk.example.yaml` configures SDK/provider transport overlays. It does not
  override per-agent request models; use `AgentSpec.llm_config.model`.
- For real provider audit, `NodeReport.usage` should preserve `model`,
  `request_id`, `provider`, and token counts when available.
- `AgentSpec.llm_config.tool_choice` is passed through by default. Use
  `RuntimeConfig.tool_choice_after_tool_result="none"` only as an explicit
  provider compatibility switch when a forced first tool call keeps looping.
- `max_dynamic_nodes` bounds Dynamic DAG preview. Do not accept unbounded model
  generated graphs.
- never commit real `.env`, provider credentials, or environment-specific overlay files.
