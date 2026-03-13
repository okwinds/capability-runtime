from __future__ import annotations

"""Runtime service façade / session continuity bridge."""

import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from .host_toolkit.history import HistoryAssembler
from .host_toolkit.turn_delta import TurnDelta
from .protocol.capability import CapabilityResult
from .protocol.context import ExecutionContext
from .runtime import Runtime
from .ui_events.transport import encode_json_line
from .ui_events.v1 import StreamLevel


@dataclass(frozen=True)
class RuntimeSession:
    """
    运行时会话上下文。

    参数：
    - session_id：宿主会话 ID
    - host_turn_id：可选宿主 turn ID
    - history：显式 continuity history
    - metadata：宿主会话元数据
    """

    session_id: str
    host_turn_id: str | None = None
    history: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeServiceRequest:
    """
    service façade 请求。

    参数：
    - capability_id：目标能力 ID
    - input：输入 payload
    - session：可选会话
    - stream_level：事件流等级（`ui`/`lite`）
    - transport：传输 framing（`jsonl`/`sse`）
    """

    capability_id: str
    input: dict[str, Any]
    session: RuntimeSession | None = None
    stream_level: str = "ui"
    transport: str = "jsonl"


@dataclass(frozen=True)
class RuntimeServiceHandle:
    """
    service 调用句柄。

    参数：
    - run_id：运行 ID
    - session_id：可选会话 ID
    - capability_id：能力 ID
    """

    run_id: str
    session_id: str | None = None
    capability_id: str = ""


def build_session_context(
    *,
    session: RuntimeSession | None,
    turn_deltas: list[TurnDelta] | None = None,
) -> dict[str, Any]:
    """
    构造 continuity 注入 overlay。

    参数：
    - session：显式会话
    - turn_deltas：可选 TurnDelta 列表；存在时优先组装 `initial_history`
    """

    history: list[dict[str, Any]] = []
    if turn_deltas:
        history = HistoryAssembler().build_initial_history(deltas=turn_deltas)
    elif session is not None:
        history = [dict(item) for item in session.history]

    host_meta: dict[str, Any] = {}
    if session is not None:
        host_meta["session_id"] = session.session_id
        if session.host_turn_id is not None:
            host_meta["host_turn_id"] = session.host_turn_id
        if session.metadata:
            host_meta["metadata"] = dict(session.metadata)
    elif turn_deltas:
        latest = turn_deltas[-1]
        if latest.session_id is not None:
            host_meta["session_id"] = latest.session_id
        if latest.host_turn_id is not None:
            host_meta["host_turn_id"] = latest.host_turn_id

    if history:
        host_meta["initial_history"] = history

    return {"__host_meta__": host_meta} if host_meta else {}


class RuntimeServiceFacade:
    """
    运行时 service façade。

    说明：
    - `start()` 负责稳定化 `run_id/session_id`
    - `run()` 负责非流式调用
    - `stream()` 负责 UI events 的 JSONL/SSE framing
    """

    def __init__(self, runtime: Runtime) -> None:
        self._runtime = runtime
        self._handles: dict[str, tuple[RuntimeServiceRequest, ExecutionContext]] = {}

    async def start(self, request: RuntimeServiceRequest) -> RuntimeServiceHandle:
        """
        初始化一次 service 调用并返回句柄。

        参数：
        - request：service façade 请求
        """

        run_id = uuid.uuid4().hex
        context = self._build_context(run_id=run_id, request=request)
        handle = RuntimeServiceHandle(
            run_id=run_id,
            session_id=request.session.session_id if request.session is not None else None,
            capability_id=request.capability_id,
        )
        self._handles[handle.run_id] = (request, context)
        return handle

    async def run(self, request: RuntimeServiceRequest) -> CapabilityResult:
        """
        执行一次非流式 service 调用。

        参数：
        - request：service façade 请求
        """

        context = self._build_context(run_id=uuid.uuid4().hex, request=request)
        return await self._runtime.run(request.capability_id, input=request.input, context=context)

    async def stream(self, handle: RuntimeServiceHandle) -> AsyncIterator[str]:
        """
        基于句柄输出 JSONL / SSE 子集文本流。

        参数：
        - handle：`start()` 返回的 service handle
        """

        stored = self._handles.get(handle.run_id)
        if stored is None:
            raise KeyError(f"Unknown runtime service handle: {handle.run_id!r}")

        request, context = stored
        level = self._resolve_stream_level(request.stream_level)
        use_sse = str(request.transport or "jsonl").strip().lower() == "sse"

        session = self._runtime.start_ui_events_session(
            request.capability_id,
            input=request.input,
            context=context,
            level=level,
        )
        async for ev in session.subscribe(after_id=None):
            yield encode_json_line(ev, prefix_data=use_sse)

    def _build_context(self, *, run_id: str, request: RuntimeServiceRequest) -> ExecutionContext:
        """
        为 service request 构造 ExecutionContext。

        参数：
        - run_id：目标运行 ID
        - request：service façade 请求
        """

        context = ExecutionContext(run_id=run_id, max_depth=self._runtime.config.max_depth)
        overlay = build_session_context(session=request.session, turn_deltas=None)
        if overlay:
            context = context.with_bag_overlay(**overlay)
        return context

    def _resolve_stream_level(self, level: str) -> StreamLevel:
        """
        解析字符串 stream level。

        参数：
        - level：字符串等级
        """

        normalized = str(level or "ui").strip().lower()
        if normalized == "lite":
            return StreamLevel.LITE
        return StreamLevel.UI
