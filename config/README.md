<div align="center">

[English](README.md) | [中文](README.zh-CN.md)

</div>

# config/

This directory contains example configuration shapes for `capability-runtime`.

Important boundaries:

- the repository exposes `Runtime` and `RuntimeConfig` as the public entrypoint
- example YAML files describe shapes, not secrets
- runtime-only objects such as approval providers or upstream requester agents are still
  injected by host code, not by static YAML
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
