# Workspace / Recall 预览

这是 runtime context pack bridge 的离线确定性示例。

示例不会把上游 Workspace 原生对象暴露给下游；它只构造本仓中立
`RuntimeRecallContextPack`，写入脱敏后的 `NodeReport` 摘要，并打印 record
reference。

运行：

```bash
python examples/08_workspace_recall_preview/run.py
```
