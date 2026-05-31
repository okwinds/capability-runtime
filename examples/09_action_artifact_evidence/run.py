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

from capability_runtime.reporting.node_report import NodeReportBuilder
from skills_runtime.core.contracts import AgentEvent


def ev(event_type: str, payload: dict) -> AgentEvent:
    return AgentEvent(type=event_type, timestamp="2026-05-31T00:00:00Z", run_id="run-artifact", payload=payload)


def main() -> None:
    raw_body = "RAW_ARTIFACT_BODY_SHOULD_NOT_APPEAR"
    report = NodeReportBuilder().build(
        events=[
            ev("tool_call_requested", {"call_id": "call-1", "name": "runtime_action", "arguments": {}}),
            ev(
                "tool_call_finished",
                {
                    "call_id": "call-1",
                    "tool": "runtime_action",
                    "result": {
                        "ok": True,
                        "data": {
                            "model_digest": "pwd completed",
                            "raw_body": raw_body,
                            "artifact_refs": [
                                {
                                    "artifact_id": "artifact-1",
                                    "action_call_id": "call-1",
                                    "artifact_type": "stdout",
                                    "label": "pwd stdout",
                                    "media_type": "text/plain",
                                    "source": "runtime_action",
                                    "preview": raw_body,
                                    "value": raw_body,
                                }
                            ],
                        },
                    },
                },
            ),
        ]
    )
    dumped = repr(report)
    assert raw_body not in dumped

    print("=== 09_action_artifact_evidence ===")
    print(f"artifact_refs={report.artifacts}")
    print(f"summary_count={len(report.meta.get('agently_action_artifacts', []))}")
    print(f"raw_body_present={raw_body in dumped}")
    print("tools_execution_model_replaced=false")


if __name__ == "__main__":
    main()
