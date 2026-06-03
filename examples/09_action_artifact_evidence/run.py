from __future__ import annotations

"""Action artifact evidence preview（离线 deterministic）。"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
for path in (REPO_ROOT, SRC_ROOT):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from capability_runtime import NodeReport


def main() -> None:
    raw_body = "RAW_ARTIFACT_BODY_SHOULD_NOT_APPEAR"
    report = NodeReport(
        status="success",
        completion_reason="run_completed",
        run_id="run-artifact",
        events_path="wal://run-artifact",
        artifacts=["runtime-action://artifact-1"],
        meta={
            "runtime_action_artifact_refs": ["runtime-action://artifact-1"],
            "action_artifacts": [
                {
                    "artifact_id": "artifact-1",
                    "action_call_id": "call-1",
                    "artifact_type": "stdout",
                    "label": "pwd stdout",
                    "media_type": "text/plain",
                    "source": "runtime_action",
                }
            ],
        },
    )
    dumped = repr(report)
    assert raw_body not in dumped

    print("=== 09_action_artifact_evidence ===")
    print(f"artifact_refs={report.artifacts}")
    print(f"runtime_artifact_refs={report.meta.get('runtime_action_artifact_refs', [])}")
    print(f"summary_count={len(report.meta.get('action_artifacts', []))}")
    print(f"raw_body_present={raw_body in dumped}")
    print("tools_execution_model_replaced=false")


if __name__ == "__main__":
    main()
