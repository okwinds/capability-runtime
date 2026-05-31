# Action Artifact Evidence

这是 runtime action artifact evidence bridge 的离线确定性示例。

示例读取本仓 `NodeReport` 中的 artifact 摘要。输出保留兼容旧下游的
`NodeReport.artifacts` locator，同时在
`meta["runtime_action_artifact_refs"]` 与 `meta["action_artifacts"]` 中暴露
runtime-neutral 迁移面，不包含 raw artifact body。新 UI/新消费者应优先读取
中立 meta references；旧消费者可继续读取 `NodeReport.artifacts`。

运行：

```bash
python examples/09_action_artifact_evidence/run.py
```
