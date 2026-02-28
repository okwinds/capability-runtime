"""
run lifecycle（内存态）。

注意：
- 原型只做“能力验证”，默认不做持久化与多进程共享；
- 若要部署到多进程/多实例，需要把 state 与 event log 外置到 redis/pgsql 等存储（不在本期范围）。
"""

from __future__ import annotations

import asyncio
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent_sdk.core.contracts import AgentEvent
from capability_runtime.reporting.node_report import NodeReportBuilder

from .approvals import ApprovalBroker, WebHumanIOProvider
from .demo import InProcessFlowRunner, build_demo_agent
from .event_log import RunEventLog
from .models import RunEvent, RunSnapshot, RunStatus, StartFlowRequest, StartSkillTaskRequest
from .rag import RAG_DEMO_TOOL_QUERY, build_demo_rag_provider, build_rag_injected_messages, build_rag_meta
from .settings import RunMode, Settings


def _now_rfc3339() -> str:
    """返回 RFC3339 UTC 时间字符串（秒级）。"""

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class RunRecord:
    run_id: str
    status: RunStatus = "queued"
    final_output: str = ""
    node_report: Optional[Dict[str, Any]] = None
    events_path: Optional[str] = None
    error: Optional[str] = None
    event_log: RunEventLog = field(default_factory=RunEventLog)


class RunStore:
    """run 的内存存储（单进程）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: Dict[str, RunRecord] = {}

    def create(self) -> RunRecord:
        """创建一个新的 run 记录并返回。"""

        run_id = f"run_{uuid.uuid4().hex}"
        rec = RunRecord(run_id=run_id)
        with self._lock:
            self._runs[run_id] = rec
        return rec

    def get(self, run_id: str) -> Optional[RunRecord]:
        """按 run_id 获取 run 记录；不存在返回 None。"""

        with self._lock:
            return self._runs.get(run_id)


class RunService:
    """把“发起 run”变成可在 Web 上消费的生命周期与事件流。"""

    def __init__(self, *, settings: Settings) -> None:
        self._settings = settings
        self._store = RunStore()
        self._approvals = ApprovalBroker(emit_event=self._emit_from_broker)

    @property
    def store(self) -> RunStore:
        return self._store

    def _emit(self, rec: RunRecord, *, type: str, payload: Dict[str, Any]) -> None:
        """
        追加一条 run 事件到 event_log。

        参数：
        - rec：RunRecord
        - type：事件类型（字符串）
        - payload：脱敏 payload（JSONable）
        """

        rec.event_log.append(RunEvent(ts=_now_rfc3339(), run_id=rec.run_id, type=type, payload=payload))

    def _emit_from_broker(self, ev: RunEvent) -> None:
        """把 approvals broker 产生的事件写回对应 run 的 event_log。"""

        rec = self._store.get(ev.run_id)
        if rec is None:
            return
        rec.event_log.append(ev)
        # approvals 会导致 run 进入阻塞态；为便于前端展示，这里同步更新粗粒度状态
        if ev.type == "approval_requested" and rec.status == "running":
            rec.status = "waiting_approval"
        if ev.type == "approval_decided" and rec.status == "waiting_approval":
            rec.status = "running"

    def start_skill_task(self, req: StartSkillTaskRequest) -> str:
        """启动一次 skills runtime run（后台线程执行），返回 run_id。"""

        rec = self._store.create()
        self._emit(rec, type="run_queued", payload={"mode": req.mode})

        t = threading.Thread(target=self._run_skill_task_thread, args=(rec, req), daemon=True)
        t.start()
        return rec.run_id

    def start_flow(self, req: StartFlowRequest) -> str:
        """启动一次 flow run（后台线程执行），返回 run_id。"""

        rec = self._store.create()
        self._emit(rec, type="flow_queued", payload={"flow_name": req.flow_name})
        t = threading.Thread(target=self._run_flow_thread, args=(rec, req), daemon=True)
        t.start()
        return rec.run_id

    def _run_flow_thread(self, rec: RunRecord, req: StartFlowRequest) -> None:
        """后台线程：执行一个 flow（直接调用 runner）。"""

        try:
            rec.status = "running"
            self._emit(rec, type="flow_started", payload={"flow_name": req.flow_name})
            runner = InProcessFlowRunner()
            out = runner.run_flow(
                flow_name=req.flow_name,
                input=req.input,
                timeout_sec=req.timeout_sec,
                wait_for_result=req.wait_for_result,
            )
            rec.status = "completed"
            rec.final_output = ""
            rec.node_report = {"status": "success", "flow_result": out}
            self._emit(rec, type="flow_completed", payload={"flow_name": req.flow_name, "result": out})
        except Exception as exc:
            rec.status = "failed"
            rec.error = str(exc)
            self._emit(rec, type="flow_failed", payload={"error": str(exc)})
        finally:
            rec.event_log.close()

    def _run_skill_task_thread(self, rec: RunRecord, req: StartSkillTaskRequest) -> None:
        """后台线程：执行一次 skills runtime run（demo 或 real）。"""

        human_io = WebHumanIOProvider(run_id=rec.run_id, broker=self._approvals)

        try:
            rec.status = "running"
            self._emit(rec, type="run_started", payload={"mode": req.mode})

            if req.mode in ("demo", "demo_rag_pre_run", "demo_rag_tool"):
                runner = InProcessFlowRunner()
                rag_provider = build_demo_rag_provider()
                agent = build_demo_agent(
                    workspace_root=self._settings.workspace_root,
                    sdk_config_paths=self._settings.sdk_config_paths,
                    human_io=human_io,
                    runner=runner,
                    demo_mode=req.mode,
                    rag_provider=rag_provider,
                )
                events: List[AgentEvent] = []
                final_output = ""
                initial_history: Optional[List[Dict[str, Any]]] = None
                rag_meta: Optional[Dict[str, Any]] = None

                if req.mode == "demo_rag_pre_run":
                    rag_query = req.task.strip() or "RAG pre-run demo"
                    rag_top_k = 2
                    rag_result = rag_provider.retrieve(query=rag_query, top_k=rag_top_k)
                    initial_history = build_rag_injected_messages(query=rag_query, rag_result=rag_result)
                    rag_meta = build_rag_meta(
                        mode="pre_run",
                        query=rag_query,
                        top_k=rag_top_k,
                        rag_result=rag_result,
                    )
                elif req.mode == "demo_rag_tool":
                    rag_query = RAG_DEMO_TOOL_QUERY
                    rag_top_k = 2
                    rag_result = rag_provider.retrieve(query=rag_query, top_k=rag_top_k)
                    rag_meta = build_rag_meta(
                        mode="tool",
                        query=rag_query,
                        top_k=rag_top_k,
                        rag_result=rag_result,
                    )

                async def _run() -> None:
                    nonlocal final_output
                    async for ev in agent.run_stream_async(req.task, run_id=rec.run_id, initial_history=initial_history):
                        events.append(ev)
                        # 脱敏展示：只把事件类型与少量字段推给前端
                        self._emit(rec, type=f"sdk:{ev.type}", payload={"event_type": ev.type})
                        if ev.type == "run_completed":
                            final_output = str((ev.payload or {}).get("final_output") or "")
                        if ev.type in ("run_failed", "run_cancelled"):
                            final_output = str((ev.payload or {}).get("message") or "")

                asyncio.run(_run())
                report = NodeReportBuilder().build(events=events)
                if rag_meta is not None:
                    report.meta["rag"] = rag_meta
                rec.final_output = final_output
                rec.node_report = report.model_dump(by_alias=True)
                rec.events_path = report.events_path
                rec.status = "completed"
                self._emit(rec, type="run_completed", payload={"events_path": report.events_path})
            else:
                # real：可选集成冒烟入口（需要安装 agently 并具备真实 requester 配置）
                try:
                    import agently as agently_mod  # type: ignore
                except ModuleNotFoundError as exc:
                    raise RuntimeError("agently is not installed; cannot run in real mode") from exc

                from capability_runtime.runtime import Runtime, RuntimeConfig

                agently_agent = agently_mod.Agently.create_agent("agently-skills-web-prototype")
                rt = Runtime(
                    agently_agent=agently_agent,
                    triggerflow_runner=InProcessFlowRunner(),
                    config=RuntimeConfig(
                        workspace_root=self._settings.workspace_root,
                        config_paths=list(self._settings.sdk_config_paths),
                        preflight_mode="error",
                        backend_mode="agently_openai_compatible",
                        upstream_verification_mode="warn",
                    ),
                    human_io=human_io,
                    approval_provider=None,
                )
                result = asyncio.run(rt.run_async(req.task, run_id=rec.run_id))
                rec.final_output = result.final_output
                rec.node_report = result.node_report.model_dump(by_alias=True)
                rec.events_path = result.events_path
                rec.status = "completed"
                self._emit(rec, type="run_completed", payload={"events_path": result.events_path})

        except Exception as exc:
            rec.status = "failed"
            rec.error = str(exc)
            self._emit(rec, type="run_failed", payload={"error": str(exc), "trace": traceback.format_exc()})
        finally:
            rec.event_log.close()

    def get_snapshot(self, run_id: str) -> Optional[RunSnapshot]:
        """返回 run 的可轮询快照；不存在返回 None。"""

        rec = self._store.get(run_id)
        if rec is None:
            return None
        return RunSnapshot(
            run_id=rec.run_id,
            status=rec.status,
            final_output=rec.final_output,
            node_report=rec.node_report,
            events_path=rec.events_path,
            error=rec.error,
        )

    def list_pending_approvals(self) -> List[Dict[str, Any]]:
        """列出当前 pending approvals（脱敏）。"""

        return [item.model_dump() for item in self._approvals.list_pending()]

    def decide_approval(self, *, approval_id: str, decision: str, reason: str) -> bool:
        """提交审批决定；返回是否命中一个 pending approval。"""

        return self._approvals.decide(approval_id=approval_id, decision=decision, reason=reason)
