<div align="center">

[English](README.md) | [中文](README.zh-CN.md)

</div>

# Workspace / Recall Preview

Offline deterministic example for the runtime context pack bridge.

The example does not expose an upstream Workspace object to downstream code. It
builds a neutral `RuntimeRecallContextPack`, writes a sanitized `NodeReport`
summary, and prints only record references.

Run:

```bash
python examples/08_workspace_recall_preview/run.py
```
