from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional, Set

from skills_runtime.core.contracts import AgentEvent

from ..protocol.capability import CapabilityResult, CapabilityStatus
from ..protocol.context import ExecutionContext
from .projector import RuntimeUIEventProjector, _AgentCtx
from .store import AfterIdExpiredError, InMemoryRuntimeEventStore
from .v1 import RuntimeEvent, StreamLevel


@dataclass(frozen=True)
class ResumeErrorInfo:
    after_id: str
    min_rid: Optional[str]
    max_rid: Optional[str]


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
        store: InMemoryRuntimeEventStore,
        heartbeat_interval_s: float,
    ) -> None:
        self._runtime = runtime
        self._capability_id = str(capability_id)
        self._input = dict(input or {})
        self._context = context
        self._level = level
        self._store = store
        self._heartbeat_interval_s = float(heartbeat_interval_s)

        self._projector = RuntimeUIEventProjector(run_id=self._context.run_id, level=self._level)
        self._in_q: asyncio.Queue = asyncio.Queue()
        self._subs: Set[asyncio.Queue] = set()
        self._started = False
        self._done = asyncio.Event()

    @property
    def run_id(self) -> str:
        return self._context.run_id

    @property
    def store(self) -> InMemoryRuntimeEventStore:
        return self._store

    def _publish_nowait(self, ev: RuntimeEvent) -> None:
        self._store.append(ev)
        for q in list(self._subs):
            try:
                q.put_nowait(ev)
            except Exception:
                pass

    def _emit_resume_error(self, *, info: ResumeErrorInfo) -> RuntimeEvent:
        msg = (
            f"after_id expired or not found: {info.after_id!r} "
            f"(available: {info.min_rid!r}..{info.max_rid!r})"
        )
        return self._projector.error(kind="after_id_expired", message=msg)

    async def _ensure_started(self) -> None:
        if self._started:
            return
        self._started = True

        def _tap(agent_ev: AgentEvent, tap_ctx: Dict[str, Any]) -> None:
            self._in_q.put_nowait(("agent_event", agent_ev, tap_ctx))

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
                            step_id=str(tap_ctx.get("step_id")) if isinstance(tap_ctx.get("step_id"), str) else None,
                            branch_id=str(tap_ctx.get("branch_id")) if isinstance(tap_ctx.get("branch_id"), str) else None,
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

    async def subscribe(self, *, after_id: Optional[str]) -> AsyncIterator[RuntimeEvent]:
        await self._ensure_started()
        q: asyncio.Queue = asyncio.Queue()
        self._subs.add(q)
        try:
            try:
                replay = list(self._store.read_after(after_id=after_id))
            except AfterIdExpiredError as exc:
                err = self._emit_resume_error(
                    info=ResumeErrorInfo(after_id=exc.after_id, min_rid=exc.min_rid, max_rid=exc.max_rid)
                )
                self._publish_nowait(err)
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
                if ev.seq <= last_seq:
                    continue
                last_seq = ev.seq
                yield ev
                if ev.type == "run.status" and ev.data.get("status") != "running":
                    return
        finally:
            self._subs.discard(q)

