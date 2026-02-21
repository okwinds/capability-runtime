"""框架验证原型服务（FastAPI + SSE）。"""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Literal, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from agently_skills_runtime.adapters.agent_adapter import AgentAdapter
from agently_skills_runtime.adapters.skill_adapter import SkillAdapter
from agently_skills_runtime.protocol.capability import CapabilityKind, CapabilityStatus
from agently_skills_runtime.runtime.engine import CapabilityRuntime, RuntimeConfig

try:
    from .instrumented import InstrumentedAdapter, InstrumentedWorkflowAdapter, RunEventBus
    from .llm_runner import create_llm_runner
    from .mock_adapter import PrototypeMockAdapter
    from .specs import ALL_SPECS
except ImportError:  # pragma: no cover - 兼容 `python server.py`
    from instrumented import InstrumentedAdapter, InstrumentedWorkflowAdapter, RunEventBus
    from llm_runner import create_llm_runner
    from mock_adapter import PrototypeMockAdapter
    from specs import ALL_SPECS


BASE_DIR = Path(__file__).resolve().parent
FRONTEND_FILE = BASE_DIR / "frontend" / "index.html"


class ConfigUpdate(BaseModel):
    """LLM 配置更新请求。"""

    base_url: Optional[str] = Field(default=None)
    api_key: Optional[str] = Field(default=None)
    model: Optional[str] = Field(default=None)


class ModeUpdate(BaseModel):
    """运行模式切换请求。"""

    mode: Literal["mock", "real"]


class RunRequest(BaseModel):
    """执行请求。"""

    scenario: Literal["neutral", "critical", "positive", "custom"]
    custom_input: Optional[str] = None


@dataclass
class LLMConfig:
    """后端内存配置（不落盘）。"""

    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"


@dataclass
class RunState:
    """单次运行状态快照。"""

    run_id: str
    scenario: str
    mode: str
    status: str
    started_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None
    output: Optional[Dict[str, Any]] = None


class PrototypeState:
    """原型后端状态容器。"""

    def __init__(self) -> None:
        """初始化全局状态。"""
        self.mode: str = "mock"
        self.config = LLMConfig()
        self.runtime: Optional[CapabilityRuntime] = None
        self.event_bus = RunEventBus()
        self.run_states: Dict[str, RunState] = {}
        self._runtime_lock = asyncio.Lock()

    async def ensure_runtime(self) -> CapabilityRuntime:
        """确保 runtime 已初始化。"""
        async with self._runtime_lock:
            if self.runtime is None:
                self.runtime = await self._build_runtime()
            return self.runtime

    async def rebuild_runtime(self) -> CapabilityRuntime:
        """按当前 mode/config 重建 runtime。"""
        async with self._runtime_lock:
            self.runtime = await self._build_runtime()
            return self.runtime

    async def _build_runtime(self) -> CapabilityRuntime:
        """构建并校验 runtime（13 能力 + 3 类 adapter）。"""
        runtime = CapabilityRuntime(config=RuntimeConfig(max_depth=12))

        workflow_adapter = InstrumentedWorkflowAdapter(event_bus=self.event_bus)
        skill_adapter = InstrumentedAdapter(
            inner=SkillAdapter(workspace_root=str(BASE_DIR)),
            event_bus=self.event_bus,
        )

        if self.mode == "mock":
            agent_inner = PrototypeMockAdapter()
        else:
            self._validate_real_mode_config()
            runner = await create_llm_runner(
                self.config.base_url,
                self.config.api_key,
                self.config.model,
            )
            agent_inner = AgentAdapter(runner=runner)

        agent_adapter = InstrumentedAdapter(inner=agent_inner, event_bus=self.event_bus)

        runtime.set_adapter(CapabilityKind.WORKFLOW, workflow_adapter)
        runtime.set_adapter(CapabilityKind.SKILL, skill_adapter)
        runtime.set_adapter(CapabilityKind.AGENT, agent_adapter)
        runtime.register_many(ALL_SPECS)

        missing = runtime.validate()
        if missing:
            raise RuntimeError(f"Runtime validation failed, missing dependencies: {missing}")

        return runtime

    def _validate_real_mode_config(self) -> None:
        """校验 real 模式必填配置。"""
        missing = []
        if not self.config.base_url.strip():
            missing.append("base_url")
        if not self.config.api_key.strip():
            missing.append("api_key")
        if not self.config.model.strip():
            missing.append("model")
        if missing:
            raise ValueError(f"real mode missing config fields: {', '.join(missing)}")

    def public_config(self) -> Dict[str, Any]:
        """返回可对外暴露的配置（不含明文 api_key）。"""
        return {
            "mode": self.mode,
            "base_url": self.config.base_url,
            "model": self.config.model,
            "api_key_present": bool(self.config.api_key),
        }


app = FastAPI(title="agently-skills-runtime prototype validation")
STATE = PrototypeState()


@app.on_event("startup")
async def _on_startup() -> None:
    """服务启动时预热 runtime。"""
    await STATE.ensure_runtime()


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """返回单文件前端页面。"""
    if not FRONTEND_FILE.exists():
        raise HTTPException(status_code=500, detail="frontend/index.html not found")
    return HTMLResponse(FRONTEND_FILE.read_text(encoding="utf-8"))


@app.get("/api/capabilities")
async def api_capabilities() -> Dict[str, Any]:
    """返回 13 个能力注册表。"""
    runtime = await STATE.ensure_runtime()
    capabilities = []
    for spec in runtime.registry.list_all():
        base = spec.base
        capabilities.append(
            {
                "id": base.id,
                "kind": base.kind.value,
                "name": base.name,
                "description": base.description,
            }
        )
    capabilities.sort(key=lambda item: (item["kind"], item["id"]))
    return {
        "count": len(capabilities),
        "missing": runtime.validate(),
        "capabilities": capabilities,
    }


@app.get("/api/config")
async def api_get_config() -> Dict[str, Any]:
    """读取当前模式与脱敏配置。"""
    return STATE.public_config()


@app.post("/api/config")
async def api_update_config(payload: ConfigUpdate) -> Dict[str, Any]:
    """更新配置并在 real 模式下立即重建 runtime。"""
    if payload.base_url is not None:
        STATE.config.base_url = payload.base_url.strip()
    if payload.api_key is not None:
        STATE.config.api_key = payload.api_key.strip()
    if payload.model is not None:
        STATE.config.model = payload.model.strip()

    if STATE.mode == "real":
        try:
            await STATE.rebuild_runtime()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover - 运行态异常
            raise HTTPException(status_code=500, detail=f"rebuild runtime failed: {exc}") from exc

    return {"message": "config saved", **STATE.public_config()}


@app.post("/api/mode")
async def api_switch_mode(payload: ModeUpdate) -> Dict[str, Any]:
    """切换 mock/real 模式并重建 runtime。"""
    old_mode = STATE.mode
    STATE.mode = payload.mode
    try:
        await STATE.rebuild_runtime()
    except ValueError as exc:
        STATE.mode = old_mode
        await STATE.rebuild_runtime()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - 运行态异常
        STATE.mode = old_mode
        await STATE.rebuild_runtime()
        raise HTTPException(status_code=500, detail=f"switch mode failed: {exc}") from exc

    return {"message": "mode switched", **STATE.public_config()}


@app.post("/api/run")
async def api_run(payload: RunRequest) -> Dict[str, Any]:
    """启动一次异步工作流运行并返回 run_id。"""
    runtime = await STATE.ensure_runtime()
    context_bag = _build_context_bag(payload)
    run_id = uuid.uuid4().hex

    STATE.run_states[run_id] = RunState(
        run_id=run_id,
        scenario=payload.scenario,
        mode=STATE.mode,
        status="running",
        started_at=_iso_now(),
    )
    await STATE.event_bus.ensure_run(run_id)

    asyncio.create_task(
        _execute_run(
            run_id=run_id,
            runtime=runtime,
            context_bag=context_bag,
        )
    )

    return {
        "run_id": run_id,
        "status": "running",
        "mode": STATE.mode,
        "scenario": payload.scenario,
    }


@app.get("/api/run/{run_id}")
async def api_get_run(run_id: str) -> Dict[str, Any]:
    """读取单次运行状态。"""
    run_state = STATE.run_states.get(run_id)
    if run_state is None:
        raise HTTPException(status_code=404, detail=f"run_id not found: {run_id}")

    payload = asdict(run_state)
    payload["event_count"] = len(STATE.event_bus.get_history(run_id))
    return payload


@app.get("/api/run/{run_id}/events")
async def api_run_events(run_id: str, request: Request) -> StreamingResponse:
    """SSE 事件流（支持 Last-Event-ID 断线回放）。"""
    if run_id not in STATE.run_states:
        raise HTTPException(status_code=404, detail=f"run_id not found: {run_id}")

    last_event_id = _parse_last_event_id(
        request.headers.get("last-event-id")
        or request.query_params.get("last_event_id")
    )

    async def stream():
        """流式回放历史并订阅实时事件。"""
        history = STATE.event_bus.get_history(run_id, after_id=last_event_id)
        for record in history:
            yield _format_sse(record)

        queue = await STATE.event_bus.subscribe(run_id)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    record = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield _format_sse(
                    {"id": record.id, "event": record.event, "data": record.data}
                )
        finally:
            await STATE.event_bus.unsubscribe(run_id, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _execute_run(
    *,
    run_id: str,
    runtime: CapabilityRuntime,
    context_bag: Dict[str, Any],
) -> None:
    """后台执行工作流，并更新 run 状态。"""
    run_state = STATE.run_states[run_id]
    try:
        result = await runtime.run(
            "content-analysis",
            run_id=run_id,
            context_bag=context_bag,
        )
    except Exception as exc:  # pragma: no cover - 运行态异常
        run_state.status = "failed"
        run_state.error = f"{type(exc).__name__}: {exc}"
        run_state.completed_at = _iso_now()
        await STATE.event_bus.publish(
            run_id,
            "error",
            {"message": run_state.error},
        )
        await _ensure_terminal_workflow_event(run_id, status="failed", error=run_state.error)
        return

    if result.status == CapabilityStatus.SUCCESS:
        run_state.status = "success"
        run_state.output = result.output if isinstance(result.output, dict) else {"output": result.output}
    else:
        run_state.status = "failed"
        run_state.error = result.error or "workflow failed"
        await STATE.event_bus.publish(
            run_id,
            "error",
            {"message": run_state.error},
        )
    run_state.completed_at = _iso_now()

    if run_state.status != "success":
        await _ensure_terminal_workflow_event(run_id, status="failed", error=run_state.error)


async def _ensure_terminal_workflow_event(
    run_id: str,
    *,
    status: str,
    error: Optional[str],
) -> None:
    """在异常路径兜底补发 workflow_complete 事件。"""
    history = STATE.event_bus.get_history(run_id)
    has_terminal = any(
        record["event"] == "workflow_complete"
        and record["data"].get("workflow_id") == "content-analysis"
        for record in history
    )
    if not has_terminal:
        await STATE.event_bus.publish(
            run_id,
            "workflow_complete",
            {
                "workflow_id": "content-analysis",
                "status": status,
                "error": error,
                "output": None,
            },
        )


def _build_context_bag(payload: RunRequest) -> Dict[str, Any]:
    """根据场景构造 context_bag。"""
    samples = {
        "neutral": (
            "Introduction: Balanced intro.\n"
            "Main Argument: Mixed strengths and weaknesses.\n"
            "Evidence: Some data, some missing sources."
        ),
        "critical": (
            "Introduction: Ambiguous framing.\n"
            "Main Argument: Unsupported claims dominate.\n"
            "Evidence: Outdated references and citation gaps."
        ),
        "positive": (
            "Introduction: Clear framing and scope.\n"
            "Main Argument: Coherent thesis with strong transitions.\n"
            "Evidence: Credible sources and up-to-date data."
        ),
    }

    if payload.scenario == "custom":
        custom = (payload.custom_input or "").strip()
        if not custom:
            raise HTTPException(status_code=400, detail="custom_input is required for custom scenario")
        raw_content = custom
    else:
        raw_content = samples[payload.scenario]

    return {
        "raw_content": raw_content,
        "analysis_depth": "standard",
        "overall_severity": payload.scenario if payload.scenario != "custom" else "neutral",
        "critical_detected": payload.scenario == "critical",
    }


def _parse_last_event_id(raw_value: Optional[str]) -> int:
    """解析 Last-Event-ID，为非法输入兜底为 0。"""
    if not raw_value:
        return 0
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return 0
    return value if value >= 0 else 0


def _format_sse(record: Dict[str, Any]) -> str:
    """把事件记录编码为 SSE 帧。"""
    return (
        f"id: {record['id']}\n"
        f"event: {record['event']}\n"
        f"data: {json.dumps(record['data'], ensure_ascii=False)}\n\n"
    )


def _iso_now() -> str:
    """返回本地时间 ISO8601 字符串。"""
    return __import__("datetime").datetime.now().isoformat()


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """统一 HTTP 错误输出格式。"""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
