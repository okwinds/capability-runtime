<div align="center">

[English](06-troubleshooting.md) | [中文](06-troubleshooting.zh-CN.md)

</div>

# Troubleshooting

- `Capability not found`
  - The capability was not registered or `Runtime.validate()` still reports missing dependencies.
- preflight failure
  - Check `sdk_config_paths`, `skills_config`, and the requested mode.
- missing `NodeReport`
  - `mock` mode may not produce the same evidence depth as `bridge` / `sdk_native`.
- `INVALID_PROMPT_MESSAGES`
  - Check `_runtime_prompt.messages` when using `precomposed_messages`.
  - For multimodal input, `content` must be either a string or a non-empty list
    of supported content parts.
  - v1 supports only `text` and `image_url` parts. Unknown fields, unknown part
    types, invalid `image_url.detail`, empty URLs, non-finite numbers, and
    non-JSON-compatible message values fail fast.
- waiting for approval
  - inspect `HostRunSnapshot` or `NodeReport` for the approval key and tool metadata.
- doc drift suspicion
  - treat `src/capability_runtime/__init__.py` and the package tests as the public contract truth.
