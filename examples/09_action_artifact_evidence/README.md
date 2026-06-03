# Action Artifact Evidence

Offline deterministic example for runtime action artifact evidence bridge.

The example reads a runtime-owned `NodeReport` artifact summary. The output
uses runtime-neutral `NodeReport.artifacts` locators and mirrors them in
`meta["runtime_action_artifact_refs"]` and `meta["action_artifacts"]`; it does
not include the raw artifact body. Readers may keep compatibility fallbacks for
older locators, but new writes use the runtime-owned scheme.

Run:

```bash
python examples/09_action_artifact_evidence/run.py
```
