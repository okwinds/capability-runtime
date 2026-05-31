# Action Artifact Evidence

Offline deterministic example for runtime action artifact evidence bridge.

The example reads a runtime-owned `NodeReport` artifact summary. The output
keeps legacy-compatible `NodeReport.artifacts` locators while exposing the
runtime-neutral migration surface in `meta["runtime_action_artifact_refs"]` and
`meta["action_artifacts"]`; it does not include the raw artifact body. New UI
consumers should prefer the neutral meta references, while old consumers can
continue reading `NodeReport.artifacts`.

Run:

```bash
python examples/09_action_artifact_evidence/run.py
```
