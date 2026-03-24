from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional, Set

from skills_runtime.core.contracts import AgentEvent

from ..logging_utils import log_suppressed_exception
from ..protocol.capability import CapabilityResult, CapabilityStatus
from ..protocol.context import ExecutionContext
from .projector import RuntimeUIEventProjector, _AgentCtx
from .store import AfterIdExpiredError, RuntimeEventStore
from .v1 import RuntimeEvent, StreamLevel


@dataclass(frozen=True)
class ResumeErrorInfo:
    after_id: str
    known_min_id: Optional[str]
    known_max_id: Optional[str]


class RuntimeUIEventsSession:
    """
    UI events 会话：一次 run 的事件投影与多订阅者消费。

    目标：
    - 不绑定任何 Web 框架；
    - 支持 `rid/after_id` 断线续传（exclusive）；
    - heartbeat 保活；
    - terminal status 收敛：确保订阅侧能收到终态事件。
    """

    def __init__(
        self,
        *,
        runtime: Any,
        capability_id: str,
        input: Dict[str, Any],
        context: ExecutionContext,
        level: StreamLevel,
        store: RuntimeEventStore,
        heartbeat_interval_s: float,
        input_queue_maxsize: int = 4096,
        subscriber_queue_maxsize: int = 1024,
    ) -> None:
        self._runtime = runtime
        self._capability_id = str(capability_id)
        self._input = dict(input or {})
        self._context = context
        self._level = level
        self._store = store
        self._heartbeat_interval_s = float(heartbeat_interval_s)
        if int(input_queue_maxsize) <= 0:
            raise ValueError("input_queue_maxsize must be > 0")
        if int(subscriber_queue_maxsize) <= 0:
            raise ValueError("subscriber_queue_maxsize must be > 0")
        self._input_queue_maxsize = int(input_queue_maxsize)
        self._subscriber_queue_maxsize = int(subscriber_queue_maxsize)

        self._projector = RuntimeUIEventProjector(run_id=self._context.run_id, level=self._level)
        self._in_q: asyncio.Queue = asyncio.Queue(maxsize=self._input_queue_maxsize)
        self._subs: Set[asyncio.Queue] = set()
        self._started = False
        self._done = asyncio.Event()

    @property
    def run_id(self) -> str:
        return self._context.run_id

    @property
    def store(self) -> RuntimeEventStore:
        return self._store

    def _emit_subscriber_lagged(self, *, q: asyncio.Queue) -> RuntimeEvent:
        err = self._projector.error(
            kind="subscriber_lagged",
            message="subscriber queue overflow; policy=disconnect",
            data={"queue_maxsize": int(getattr(q, "maxsize", 0) or 0), "policy": "disconnect"},
        )
        # 该错误是“订阅者局部诊断信号”，不进入 store；避免客户端误用其 rid 作为 after_id 续传游标。
        return err.model_copy(update={"rid": None})

    def _cut_off_subscriber(self, *, q: asyncio.Queue) -> None:
        self._subs.discard(q)
        try:
            while True:
                q.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            q.put_nowait(self._emit_subscriber_lagged(q=q))
        except Exception as exc:
            # fail-open：断开慢订阅者必须不影响主事件流
            log_suppressed_exception(
                context="cut_off_subscriber_emit_lagged",
                exc=exc,
                run_id=self._context.run_id if self._context else None,
            )

    def _publish_nowait(self, ev: RuntimeEvent) -> None:
        self._store.append(ev)
        for q in list(self._subs):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                self._cut_off_subscriber(q=q)
            except Exception as exc:
                # fail-open：单个订阅者的异常不得影响主事件流
                log_suppressed_exception(
                    context="publish_to_subscriber",
                    exc=exc,
                    extra={"event_type": getattr(ev, "type", None)},
                )

    def _emit_resume_error(self, *, info: ResumeErrorInfo) -> RuntimeEvent:
        msg = (
            f"after_id expired or not found: {info.after_id!r} "
            f"(available: {info.known_min_id!r}..{info.known_max_id!r})"
        )
        return self._projector.error(
            kind="after_id_expired",
            message=msg,
            data={
                "after_id": info.after_id,
                "known_min_id": info.known_min_id,
                "known_max_id": info.known_max_id,
            },
        )

    async def ensure_started(self) -> None:
        if self._started:
            return
        self._started = True

        def _tap(agent_ev: AgentEvent, tap_ctx: Dict[str, Any]) -> None:
            try:
                expected_run_id = self._context.run_id
                ctx_run_id = tap_ctx.get("run_id")
                if isinstance(ctx_run_id, str) and ctx_run_id != expected_run_id:
                    return
                ev_run_id = getattr(agent_ev, "run_id", None)
                if isinstance(ev_run_id, str) and ev_run_id != expected_run_id:
                    return
                self._in_q.put_nowait(("agent_event", agent_ev, tap_ctx))
            except asyncio.QueueFull:
                # fail-open：旁路 tap 不得影响主流程；输入队列背压时丢弃旁路事件
                pass
            except Exception as exc:
                # fail-open：旁路 tap 过滤/入队异常不得影响主流程
                log_suppressed_exception(
                    context="ui_events_tap",
                    exc=exc,
                    run_id=self._context.run_id if self._context else None,
                    extra={"event_type": getattr(agent_ev, "type", None)},
                )

        self._runtime._register_agent_event_tap(_tap)

        async def _runner() -> None:
            try:
                async for item in self._runtime.run_stream(self._capability_id, input=self._input, context=self._context):
                    if isinstance(item, dict):
                        await self._in_q.put(("workflow_event", item))
                    elif isinstance(item, CapabilityResult):
                        await self._in_q.put(("terminal", item))
                        return
                    else:
                        continue
                await self._in_q.put(("error", RuntimeError("run_stream ended without terminal CapabilityResult")))
            except Exception as exc:
                await self._in_q.put(("error", exc))

        task = asyncio.create_task(_runner())

        async def _loop() -> None:
            try:
                for ev in self._projector.start():
                    self._publish_nowait(ev)

                done = False
                while not done:
                    try:
                        item = await asyncio.wait_for(self._in_q.get(), timeout=self._heartbeat_interval_s)
                    except asyncio.TimeoutError:
                        if self._level != StreamLevel.LITE:
                            self._publish_nowait(self._projector.heartbeat())
                        continue

                    kind = item[0]
                    if kind == "agent_event":
                        agent_ev, tap_ctx = item[1], item[2]
                        agent_ctx = _AgentCtx(
                            run_id=str(tap_ctx.get("run_id") or self._context.run_id),
                            capability_id=str(tap_ctx.get("capability_id") or ""),
                            workflow_id=str(tap_ctx.get("workflow_id")) if isinstance(tap_ctx.get("workflow_id"), str) else None,
                            workflow_instance_id=str(tap_ctx.get("workflow_instance_id"))
                            if isinstance(tap_ctx.get("workflow_instance_id"), str)
                            else None,
                            step_id=str(tap_ctx.get("step_id")) if isinstance(tap_ctx.get("step_id"), str) else None,
                            branch_id=str(tap_ctx.get("branch_id")) if isinstance(tap_ctx.get("branch_id"), str) else None,
                            wf_frames=list(tap_ctx.get("wf_frames")) if isinstance(tap_ctx.get("wf_frames"), list) else None,
                        )
                        for out_ev in self._projector.on_agent_event(agent_ev, ctx=agent_ctx):
                            self._publish_nowait(out_ev)
                    elif kind == "workflow_event":
                        wf_ev = item[1]
                        for out_ev in self._projector.on_workflow_event(wf_ev):
                            self._publish_nowait(out_ev)
                    elif kind == "terminal":
                        terminal = item[1]
                        for out_ev in self._projector.on_terminal(terminal):
                            self._publish_nowait(out_ev)
                        done = True
                    elif kind == "error":
                        exc = item[1]
                        self._publish_nowait(self._projector.error(kind="runner_error", message=str(exc)))
                        for out_ev in self._projector.on_terminal(CapabilityResult(status=CapabilityStatus.FAILED, error=str(exc))):
                            self._publish_nowait(out_ev)
                        done = True
            finally:
                self._done.set()
                await task
                self._runtime._unregister_agent_event_tap(_tap)

        asyncio.create_task(_loop())

    async def wait_done(self) -> None:
        await self._done.wait()

    async def subscribe(self, *, after_id: Optional[str]) -> AsyncIterator[RuntimeEvent]:
        await self.ensure_started()
        q: asyncio.Queue = asyncio.Queue(maxsize=self._subscriber_queue_maxsize)
        self._subs.add(q)
        try:
            try:
                replay = list(self._store.read_after(after_id=after_id))
            except AfterIdExpiredError as exc:
                err = self._emit_resume_error(
                    info=ResumeErrorInfo(after_id=exc.after_id, known_min_id=exc.min_rid, known_max_id=exc.max_rid)
                )
                yield err
                return

            last_seq = replay[-1].seq if replay else 0
            for ev in replay:
                yield ev
                if ev.type == "run.status" and ev.data.get("status") != "running":
                    return

            while True:
                if self._done.is_set() and q.empty():
                    return
                ev = await q.get()
                if ev.type == "error" and ev.data.get("kind") == "subscriber_lagged":
                    yield ev
                    return
                if ev.seq <= last_seq:
                    continue
                last_seq = ev.seq
                yield ev
                if ev.type == "run.status" and ev.data.get("status") != "running":
                    return
        finally:
            self._subs.discard(q)

    async def _ensure_started(self) -> None:
        """兼容旧调用方；新代码应使用公开的 `ensure_started()`。"""

        await self.ensure_started()
