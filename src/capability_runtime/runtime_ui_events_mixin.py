from __future__ import annotations

"""Runtime 的 UI events 投影能力（mixin）。"""

import asyncio
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

from skills_runtime.core.contracts import AgentEvent

from .protocol.capability import CapabilityResult, CapabilityStatus
from .protocol.context import ExecutionContext

# UI events 队列容量上限（防止内存无界增长）
_UI_EVENTS_QUEUE_MAXSIZE = 1000


class RuntimeUIEventsMixin:
    """
    UI events 投影相关方法集合。

    说明：
    - 以 mixin 方式抽出，减少 Runtime 主类体积（便于聚焦“注册/校验/执行”主职责）。
    - 依赖 Runtime 本体持有：
      - `_config`、`_agent_event_taps`、`_register_agent_event_tap/_unregister_agent_event_tap` 等状态/方法。
    """

    _agent_event_taps: List[Any]

    def _register_agent_event_tap(self, tap: Any) -> None:
        """
        注册一个 AgentEvent 旁路 tap（内部使用）。

        参数：
        - tap：可调用对象，签名为 `(ev: AgentEvent, ctx: Dict[str, Any]) -> None`
        """

        self._agent_event_taps.append(tap)

    def _unregister_agent_event_tap(self, tap: Any) -> None:
        """反注册 AgentEvent tap（内部使用）。"""

        self._agent_event_taps = [t for t in self._agent_event_taps if t is not tap]

    def emit_agent_event_taps(self, *, ev: AgentEvent, context: ExecutionContext, capability_id: str) -> None:
        """
        将 SDK AgentEvent 分发给内部 taps（不影响对外事件流）。

        说明：
        - 只传递最小上下文信息（避免泄露 context.bag 的业务 payload）。
        """

        if not getattr(self, "_agent_event_taps", None):
            return

        def _collect_workflow_frames(ctx: ExecutionContext) -> List[Dict[str, str]]:
            """
            从当前 context 向上回溯 parent_context，收集 workflow 嵌套链的最小信息。

            设计目标：
            - 不依赖“在 bag 里维护可变栈”（child() 的 bag 是浅拷贝，list 会共享引用）；
            - 通过 `__wf_workflow_instance_id`（若存在）进行 frame 分段，支持递归/重入；
            - 以最小字段（workflow_id/workflow_instance_id/step_id/branch_id）供 UI projector 组装 path。
            """

            frames_inner_to_outer: List[Dict[str, str]] = []
            last_frame_key: Optional[str] = None
            cur: Optional[ExecutionContext] = ctx
            while cur is not None:
                bag = dict(getattr(cur, "bag", {}) or {})

                wf_id = bag.get("__wf_workflow_id")
                wf_inst = bag.get("__wf_workflow_instance_id")
                step_id = bag.get("__wf_step_id")
                branch_id = bag.get("__wf_branch_id")

                wf_id_s = wf_id.strip() if isinstance(wf_id, str) else ""
                wf_inst_s = wf_inst.strip() if isinstance(wf_inst, str) else ""
                step_id_s = step_id.strip() if isinstance(step_id, str) else ""
                branch_id_s = branch_id.strip() if isinstance(branch_id, str) else ""

                key = wf_inst_s or wf_id_s
                if key and key != last_frame_key:
                    frame: Dict[str, str] = {}
                    if wf_id_s:
                        frame["workflow_id"] = wf_id_s
                    if wf_inst_s:
                        frame["workflow_instance_id"] = wf_inst_s
                    if step_id_s:
                        frame["step_id"] = step_id_s
                    if branch_id_s:
                        frame["branch_id"] = branch_id_s
                    frames_inner_to_outer.append(frame)
                    last_frame_key = key

                cur = getattr(cur, "parent_context", None)

            return list(reversed(frames_inner_to_outer))

        bag = dict(getattr(context, "bag", {}) or {})
        tap_ctx: Dict[str, Any] = {"run_id": context.run_id, "capability_id": capability_id}
        for k, out_key in (
            ("__wf_workflow_id", "workflow_id"),
            ("__wf_workflow_instance_id", "workflow_instance_id"),
            ("__wf_step_id", "step_id"),
            ("__wf_branch_id", "branch_id"),
        ):
            v = bag.get(k)
            if isinstance(v, str) and v.strip():
                tap_ctx[out_key] = v.strip()

        frames = _collect_workflow_frames(context)
        if frames:
            tap_ctx["wf_frames"] = frames

        for t in list(self._agent_event_taps):
            try:
                t(ev, tap_ctx)
            except Exception:
                # 旁路 tap 不得影响主流程（fail-open）
                pass

    async def run_ui_events(
        self,
        capability_id: str,
        *,
        input: Optional[Dict[str, Any]] = None,
        context: Optional[ExecutionContext] = None,
        level: Any = None,
        heartbeat_interval_s: float = 15.0,
    ) -> AsyncIterator[Any]:
        """
        UI events 流式执行：输出 RuntimeEvent v1（Envelope/path/levels/types）。

        说明：
        - 不改变现有 `run_stream()` 对外行为；这是新增的投影层输出；
        - UI events 不是审计真相源；证据链仍以 NodeReport/WAL 为准；
        - `rid` 默认等于 `seq` 的字符串，支持 after_id exclusive 的最小实现。
        - 投影输入来源（事实）：
          - workflow 轻量事件与终态 `CapabilityResult`：通过消费 `run_stream()` 获取；
          - 上游 `AgentEvent`：通过内部 tap 旁路收集（避免重复投影，并支持 workflow 内部 Agent 的 deep stream）。
        """

        from .ui_events.projector import RuntimeUIEventProjector, _AgentCtx
        from .ui_events.v1 import StreamLevel

        ctx = context or ExecutionContext(run_id=uuid.uuid4().hex, max_depth=self._config.max_depth)  # type: ignore[attr-defined]
        lv = level if isinstance(level, StreamLevel) else StreamLevel.UI
        projector = RuntimeUIEventProjector(run_id=ctx.run_id, level=lv)

        q: asyncio.Queue = asyncio.Queue(maxsize=_UI_EVENTS_QUEUE_MAXSIZE)
        done = False

        def _tap(agent_ev: AgentEvent, tap_ctx: Dict[str, Any]) -> None:
            # run_ui_events 仅服务于单一 run：必须在入队前过滤其它 run 的旁路 AgentEvent，
            # 避免无关事件进入队列导致堆积/背压（参见 docs/specs/runtime-ui-events-v1.md）。
            if str(tap_ctx.get("run_id") or "") != str(ctx.run_id):
                return
            try:
                q.put_nowait(("agent_event", agent_ev, tap_ctx))
            except asyncio.QueueFull:
                # 队列满时静默丢弃（fail-open）；UI events 不是审计真相源
                pass

        self._register_agent_event_tap(_tap)

        async def _runner() -> None:
            try:
                async for item in self.run_stream(capability_id, input=input, context=ctx):  # type: ignore[attr-defined]
                    if isinstance(item, dict):
                        await q.put(("workflow_event", item))
                    elif isinstance(item, CapabilityResult):
                        await q.put(("terminal", item))
                        return
                    else:
                        # AgentEvent：由 tap 旁路处理，避免重复投影
                        continue
            except Exception as exc:
                await q.put(("error", exc))

        task = asyncio.create_task(_runner())
        try:
            for ev in projector.start():
                yield ev

            while not done:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=float(heartbeat_interval_s))
                except asyncio.TimeoutError:
                    if lv != StreamLevel.LITE:
                        yield projector.heartbeat()
                    continue

                kind = item[0]
                if kind == "agent_event":
                    agent_ev, tap_ctx = item[1], item[2]
                    agent_ctx = _AgentCtx(
                        run_id=str(tap_ctx.get("run_id") or ctx.run_id),
                        capability_id=str(tap_ctx.get("capability_id") or ""),
                        workflow_id=str(tap_ctx.get("workflow_id")) if isinstance(tap_ctx.get("workflow_id"), str) else None,
                        workflow_instance_id=str(tap_ctx.get("workflow_instance_id"))
                        if isinstance(tap_ctx.get("workflow_instance_id"), str)
                        else None,
                        step_id=str(tap_ctx.get("step_id")) if isinstance(tap_ctx.get("step_id"), str) else None,
                        branch_id=str(tap_ctx.get("branch_id")) if isinstance(tap_ctx.get("branch_id"), str) else None,
                        wf_frames=list(tap_ctx.get("wf_frames")) if isinstance(tap_ctx.get("wf_frames"), list) else None,
                    )
                    for out_ev in projector.on_agent_event(agent_ev, ctx=agent_ctx):
                        yield out_ev
                elif kind == "workflow_event":
                    wf_ev = item[1]
                    for out_ev in projector.on_workflow_event(wf_ev):
                        yield out_ev
                elif kind == "terminal":
                    terminal = item[1]
                    for out_ev in projector.on_terminal(terminal):
                        yield out_ev
                    done = True
                elif kind == "error":
                    exc = item[1]
                    yield projector.error(kind="runner_error", message=str(exc))
                    for out_ev in projector.on_terminal(CapabilityResult(status=CapabilityStatus.FAILED, error=str(exc))):
                        yield out_ev
                    done = True

            await task
        finally:
            self._unregister_agent_event_tap(_tap)

    def start_ui_events_session(
        self,
        capability_id: str,
        *,
        input: Optional[Dict[str, Any]] = None,
        context: Optional[ExecutionContext] = None,
        level: Any = None,
        store: Any = None,
        store_max_events: int = 10_000,
        heartbeat_interval_s: float = 15.0,
    ) -> Any:
        """
        创建一次 run 的 UI events 会话（支持多订阅者 + after_id 续传）。
        """

        from .ui_events.session import RuntimeUIEventsSession
        from .ui_events.store import InMemoryRuntimeEventStore
        from .ui_events.v1 import StreamLevel

        ctx = context or ExecutionContext(run_id=uuid.uuid4().hex, max_depth=self._config.max_depth)  # type: ignore[attr-defined]
        lv = level if isinstance(level, StreamLevel) else StreamLevel.UI
        store_impl = store if store is not None else InMemoryRuntimeEventStore(max_events=int(store_max_events))
        return RuntimeUIEventsSession(
            runtime=self,
            capability_id=capability_id,
            input=input or {},
            context=ctx,
            level=lv,
            store=store_impl,
            heartbeat_interval_s=float(heartbeat_interval_s),
        )
