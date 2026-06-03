# Action Artifact Evidence

这是 runtime action artifact evidence bridge 的离线确定性示例。

示例读取本仓 `NodeReport` 中的 artifact 摘要。输出使用 runtime-neutral
`NodeReport.artifacts` locator，并在 `meta["runtime_action_artifact_refs"]` 与
`meta["action_artifacts"]` 中镜像摘要，不包含 raw artifact body。读取方可以保留
旧 locator 兼容 fallback，但新写入使用本仓 runtime-owned scheme。

运行：

```bash
python examples/09_action_artifact_evidence/run.py
```
