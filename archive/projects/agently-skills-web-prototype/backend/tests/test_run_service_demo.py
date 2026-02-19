from __future__ import annotations

import time
from pathlib import Path

from agently_skills_web_backend.models import StartSkillTaskRequest
from agently_skills_web_backend.runs import RunService
from agently_skills_web_backend.settings import Settings


def test_run_service_demo_can_complete_after_approval(tmp_path: Path):
    cfg = Path(__file__).resolve().parents[1] / "config" / "sdk.demo.yaml"
    settings = Settings(workspace_root=tmp_path / "ws", sdk_config_paths=[cfg], run_mode="demo")
    service = RunService(settings=settings)

    run_id = service.start_skill_task(StartSkillTaskRequest(task="demo task", mode="demo"))

    # 等待 pending approval 出现并批准
    approval_id = None
    for _ in range(200):
        items = service.list_pending_approvals()
        if items:
            approval_id = items[0]["approval_id"]
            break
        time.sleep(0.01)
    assert approval_id

    assert service.decide_approval(approval_id=approval_id, decision="approve", reason="ok") is True

    # 等待 run 完成
    snap = None
    for _ in range(400):
        snap = service.get_snapshot(run_id)
        if snap and snap.status in ("completed", "failed"):
            break
        time.sleep(0.01)

    assert snap is not None
    assert snap.status == "completed"
    assert snap.node_report is not None

