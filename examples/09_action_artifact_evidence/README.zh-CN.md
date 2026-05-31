# Action Artifact Evidence

这是 runtime action artifact evidence bridge 的离线确定性示例。

示例把类似上游 Action result 的 fixture 交给 `NodeReportBuilder`。输出只包含
`agently-action://...` 引用与 `meta["agently_action_artifacts"]` 摘要，不包含 raw
artifact body。

运行：

```bash
python examples/09_action_artifact_evidence/run.py
```
