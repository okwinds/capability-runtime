from __future__ import annotations

import time
from pathlib import Path

from agently_skills_web_backend.models import StartSkillTaskRequest
from agently_skills_web_backend.runs import RunService
from agently_skills_web_backend.settings import Settings


def _build_service(tmp_path: Path) -> RunService:
    """构造 backend RunService（离线 demo 配置）。"""

    cfg = Path(__file__).resolve().parents[1] / "config" / "sdk.demo.yaml"
    settings = Settings(workspace_root=tmp_path / "ws", sdk_config_paths=[cfg], run_mode="demo")
    return RunService(settings=settings)


def _wait_until_done(service: RunService, run_id: str) -> object:
    """轮询等待 run 结束并返回 snapshot。"""

    snap = None
    for _ in range(400):
        snap = service.get_snapshot(run_id)
        if snap and snap.status in ("completed", "failed"):
            break
        time.sleep(0.01)
    return snap


def test_run_service_demo_rag_pre_run_sets_meta(tmp_path: Path) -> None:
    """`demo_rag_pre_run` 应写入 `meta.rag.mode=pre_run` 且不泄露 query 原文。"""

    service = _build_service(tmp_path)
    run_id = service.start_skill_task(StartSkillTaskRequest(task="RAG pre run", mode="demo_rag_pre_run"))
    snap = _wait_until_done(service, run_id)

    assert snap is not None
    assert snap.status == "completed"
    assert snap.node_report is not None

    rag = (snap.node_report.get("meta") or {}).get("rag") or {}
    assert rag.get("mode") == "pre_run"
    query_item = (rag.get("queries") or [{}])[0]
    assert query_item.get("query_sha256")
    assert "query" not in query_item
    chunks = query_item.get("chunks") or []
    assert chunks
    for chunk in chunks:
        assert "content" not in chunk


def test_run_service_demo_rag_tool_sets_meta_and_tool_calls(tmp_path: Path) -> None:
    """`demo_rag_tool` 应写入 `meta.rag.mode=tool` 且产生 `rag_retrieve` tool evidence。"""

    service = _build_service(tmp_path)
    run_id = service.start_skill_task(StartSkillTaskRequest(task="RAG tool run", mode="demo_rag_tool"))
    snap = _wait_until_done(service, run_id)

    assert snap is not None
    assert snap.status == "completed"
    assert snap.node_report is not None

    rag = (snap.node_report.get("meta") or {}).get("rag") or {}
    assert rag.get("mode") == "tool"

    tool_calls = snap.node_report.get("tool_calls") or []
    rag_calls = [item for item in tool_calls if item.get("name") == "rag_retrieve"]
    assert len(rag_calls) == 1
