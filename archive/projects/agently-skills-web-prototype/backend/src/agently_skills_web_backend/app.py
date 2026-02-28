"""
FastAPI app：全量能力验证 Web 原型（后端）。

默认行为：
- demo 模式离线可跑（scripted LLM stream）；
- 通过 SSE 输出运行事件；
- 通过 approvals API 让人类在 Web UI 中 approve/deny（fail-closed）。
"""

from __future__ import annotations

import sys
from importlib import metadata
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .models import (
    ApprovalDecisionRequest,
    RunSnapshot,
    StartFlowRequest,
    StartRunResponse,
    StartSkillTaskRequest,
)
from .runs import RunService
from .settings import load_settings


def _pkg_version(dist_name: str) -> Optional[str]:
    """读取已安装包的版本号（未安装则返回 None）。"""

    try:
        return metadata.version(dist_name)
    except Exception:
        return None


settings = load_settings()
service = RunService(settings=settings)

app = FastAPI(title="Agently × Skills Runtime SDK Web Prototype", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/meta")
def api_meta() -> Dict[str, Any]:
    """版本与配置摘要（用于冻结核验/排障）。"""

    return {
        "python": {"version": sys.version.split()[0]},
        "packages": {
            "agently": _pkg_version("agently"),
            "skills-runtime-sdk-python": _pkg_version("skills-runtime-sdk-python"),
            "capability-runtime": _pkg_version("capability-runtime"),
        },
        "settings": {
            "workspace_root": str(settings.workspace_root),
            "sdk_config_paths": [str(p) for p in settings.sdk_config_paths],
            "run_mode": settings.run_mode,
        },
    }


@app.post("/api/runs/skill-task", response_model=StartRunResponse)
def api_start_skill_task(req: StartSkillTaskRequest) -> StartRunResponse:
    run_id = service.start_skill_task(req)
    return StartRunResponse(run_id=run_id)


@app.post("/api/runs/flow", response_model=StartRunResponse)
def api_start_flow(req: StartFlowRequest) -> StartRunResponse:
    run_id = service.start_flow(req)
    return StartRunResponse(run_id=run_id)


@app.get("/api/runs/{run_id}", response_model=RunSnapshot)
def api_get_run(run_id: str) -> RunSnapshot:
    snap = service.get_snapshot(run_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="run not found")
    return snap


@app.get("/api/runs/{run_id}/events")
def api_run_events(run_id: str):
    rec = service.store.get(run_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="run not found")

    return StreamingResponse(rec.event_log.sse_stream(), media_type="text/event-stream")


@app.get("/api/approvals/pending")
def api_list_pending_approvals():
    return {"items": service.list_pending_approvals()}


@app.post("/api/approvals/{approval_id}/decision")
def api_decide_approval(approval_id: str, req: ApprovalDecisionRequest):
    ok = service.decide_approval(approval_id=approval_id, decision=req.decision, reason=req.reason)
    if not ok:
        raise HTTPException(status_code=404, detail="approval not found")
    return {"ok": True}
