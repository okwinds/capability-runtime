<div align="center">

[English](README.md) | [中文](README.zh-CN.md)

</div>

# 06_responses_bridge

Preview example for the runtime-owned Responses bridge.

Responses is an explicit opt-in:

```python
RuntimeConfig(mode="bridge", requester_strategy="responses")
```

It is not the default. Legacy bridge behavior remains `chat_completions` when
the field is omitted.

```bash
python examples/06_responses_bridge/run.py
```
