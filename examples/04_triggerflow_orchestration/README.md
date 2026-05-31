<div align="center">

[English](README.md) | [中文](README.zh-CN.md)

</div>

# 04_triggerflow_orchestration

This English page is the default entry for open-source readers.

For full Chinese details and original context, see [README.zh-CN.md](README.zh-CN.md).

This example intentionally uses `Runtime` and `WorkflowSpec`, not a direct
upstream `TriggerFlow` import. TriggerFlow remains an internal orchestration
substrate; downstream code should consume workflow lifecycle through runtime
snapshots, NodeReport, and UI events.

## Quick Run

```bash
python examples/04_triggerflow_orchestration/run.py
```
