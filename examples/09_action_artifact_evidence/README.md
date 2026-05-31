# Action Artifact Evidence

Offline deterministic example for runtime action artifact evidence bridge.

The example feeds an upstream-action-like fixture into
`NodeReportBuilder`. The output contains `agently-action://...` references and
`meta["agently_action_artifacts"]`; it does not include the raw artifact body.

Run:

```bash
python examples/09_action_artifact_evidence/run.py
```
