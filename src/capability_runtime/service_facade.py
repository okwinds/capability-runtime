from __future__ import annotations

"""Runtime service façade / session continuity bridge."""

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal

from .host_toolkit.history import HistoryAssembler
from .host_toolkit.turn_delta import TurnDelta
from .protocol.capability import CapabilityResult, CapabilityStatus
from .protocol.context import ExecutionContext
from .runtime import Runtime
from .types import NodeReport
from .ui_events.transport import encode_json_line
from .ui_events.v1 import RuntimeEvent, StreamLevel


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
    turn_deltas: list[TurnDelta] = field(default_factory=list)
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
    execution_target: Literal["local", "rpc"] = "local"
    timeout_ms: int | None = None


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


@dataclass
class _HandleState:
    request: RuntimeServiceRequest
    context: ExecutionContext
    session: Any | None
    reaper_task: asyncio.Task[None] | None = None


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
    if turn_deltas is None and session is not None and getattr(session, "turn_deltas", None):
        raw_turn_deltas = getattr(session, "turn_deltas", None)
        if isinstance(raw_turn_deltas, list):
            turn_deltas = raw_turn_deltas
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
        self._handles: dict[str, _HandleState] = {}

    async def start(self, request: RuntimeServiceRequest) -> RuntimeServiceHandle:
        """
        初始化一次 service 调用并返回句柄。

        参数：
        - request：service façade 请求
        """

        run_id = uuid.uuid4().hex
        context = self._build_context(run_id=run_id, request=request)
        session = None
        if request.execution_target == "local":
            level = self._resolve_stream_level(request.stream_level)
            session = self._runtime.start_ui_events_session(
                request.capability_id,
                input=request.input,
                context=context,
                level=level,
            )
        else:
            self._require_runtime_client(request=request)
        handle = RuntimeServiceHandle(
            run_id=run_id,
            session_id=request.session.session_id if request.session is not None else None,
            capability_id=request.capability_id,
        )
        state = _HandleState(request=request, context=context, session=session)
        self._handles[handle.run_id] = state
        return handle

    async def run(self, request: RuntimeServiceRequest) -> CapabilityResult:
        """
        执行一次非流式 service 调用。

        参数：
        - request：service façade 请求
        """

        run_id = uuid.uuid4().hex
        context = self._build_context(run_id=run_id, request=request)
        if request.execution_target == "local":
            return await self._runtime.run(request.capability_id, input=request.input, context=context)

        client = self._require_runtime_client(request=request)
        response = await client.invoke(self._build_rpc_request_dict(run_id=run_id, request=request))
        return self._coerce_capability_result(response)

    async def stream(self, handle: RuntimeServiceHandle) -> AsyncIterator[str]:
        """
        基于句柄输出 JSONL / SSE 子集文本流。

        参数：
        - handle：`start()` 返回的 service handle
        """

        state = self._handles.get(handle.run_id)
        if state is None:
            raise KeyError(f"Unknown runtime service handle: {handle.run_id!r}")

        request = state.request
        use_sse = str(request.transport or "jsonl").strip().lower() == "sse"
        session = state.session
        if request.execution_target == "rpc":
            client = self._require_runtime_client(request=request)
            try:
                async for item in client.stream(self._build_rpc_request_dict(run_id=handle.run_id, request=request)):
                    yield self._encode_rpc_stream_item(item, use_sse=use_sse)
            finally:
                self._handles.pop(handle.run_id, None)
            return

        if state.reaper_task is None:
            state.reaper_task = asyncio.create_task(self._reap_handle_when_done(run_id=handle.run_id, session=session))
        async for ev in session.subscribe(after_id=None):
            yield encode_json_line(ev, prefix_data=use_sse)
        self._handles.pop(handle.run_id, None)

    async def cancel(self, handle: RuntimeServiceHandle) -> None:
        """
        取消一个 service 调用。
        """

        state = self._handles.get(handle.run_id)
        if state is None:
            if getattr(self._runtime.config, "runtime_client", None) is not None:
                await self._runtime.config.runtime_client.cancel(run_id=handle.run_id)
                return
            raise KeyError(f"Unknown runtime service handle: {handle.run_id!r}")

        if state.request.execution_target == "rpc":
            client = self._require_runtime_client(request=state.request)
            await client.cancel(run_id=handle.run_id)
            return

        raise NotImplementedError("local cancel is not implemented")

    async def replay(
        self,
        *,
        workflow_id: str,
        run_id: str,
        current_input: dict[str, Any],
        execution_target: Literal["local", "rpc"] = "local",
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """
        workflow replay 的最小 service façade surface。
        """

        if execution_target == "rpc":
            request = RuntimeServiceRequest(
                capability_id=workflow_id,
                input=current_input,
                execution_target="rpc",
                timeout_ms=timeout_ms,
            )
            client = self._require_runtime_client(request=request)
            response = await client.replay(self._build_rpc_request_dict(run_id=run_id, request=request))
            if not isinstance(response, dict):
                raise TypeError("runtime_client.replay() must return dict")
            return dict(response)

        result = await self._runtime.replay(
            workflow_id=workflow_id,
            run_id=run_id,
            current_input=current_input,
        )
        return self._capability_result_to_dict(result)

    def _build_context(self, *, run_id: str, request: RuntimeServiceRequest) -> ExecutionContext:
        """
        为 service request 构造 ExecutionContext。

        参数：
        - run_id：目标运行 ID
        - request：service façade 请求
        """

        context = ExecutionContext(run_id=run_id, max_depth=self._runtime.config.max_depth)
        overlay = build_session_context(
            session=request.session,
            turn_deltas=list(request.session.turn_deltas) if request.session is not None and request.session.turn_deltas else None,
        )
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

    def _require_runtime_client(self, *, request: RuntimeServiceRequest) -> Any:
        """在 RPC 目标下获取已配置的 runtime client。"""

        runtime_client = getattr(self._runtime.config, "runtime_client", None)
        if runtime_client is None:
            raise ValueError("runtime_client is required when execution_target='rpc'")
        return runtime_client

    def _build_rpc_request_dict(self, *, run_id: str, request: RuntimeServiceRequest) -> dict[str, Any]:
        """按 v1 契约构造发往 runtime client 的 request dict。"""

        return {
            "request_id": uuid.uuid4().hex,
            "run_id": run_id,
            "session_id": request.session.session_id if request.session is not None else None,
            "capability_id": request.capability_id,
            "input": dict(request.input),
            "timeout_ms": request.timeout_ms,
            "stream_level": str(request.stream_level or "ui").strip().lower() or "ui",
            "transport": str(request.transport or "jsonl").strip().lower() or "jsonl",
        }

    def _coerce_capability_result(self, payload: Any) -> CapabilityResult:
        """把 RPC 返回值收敛为 CapabilityResult。"""

        if isinstance(payload, CapabilityResult):
            return payload
        if not isinstance(payload, dict):
            raise TypeError("runtime_client.invoke() must return CapabilityResult or dict")

        status_raw = payload.get("status")
        try:
            status = status_raw if isinstance(status_raw, CapabilityStatus) else CapabilityStatus(str(status_raw))
        except Exception as exc:  # pragma: no cover - error path by contract
            raise TypeError("runtime_client.invoke() returned invalid CapabilityResult payload") from exc

        node_report_raw = payload.get("node_report")
        node_report = None
        if isinstance(node_report_raw, NodeReport):
            node_report = node_report_raw
        elif isinstance(node_report_raw, dict):
            node_report = NodeReport.model_validate(node_report_raw)
        elif node_report_raw is not None:
            raise TypeError("runtime_client.invoke() returned invalid node_report payload")

        artifacts_raw = payload.get("artifacts")
        if artifacts_raw is None:
            artifacts = []
        elif isinstance(artifacts_raw, list):
            artifacts = [str(item) for item in artifacts_raw]
        else:
            raise TypeError("runtime_client.invoke() returned invalid artifacts payload")

        metadata_raw = payload.get("metadata")
        if metadata_raw is None:
            metadata = {}
        elif isinstance(metadata_raw, dict):
            metadata = dict(metadata_raw)
        else:
            raise TypeError("runtime_client.invoke() returned invalid metadata payload")

        duration_ms = payload.get("duration_ms")
        if duration_ms is not None and not isinstance(duration_ms, (int, float)):
            raise TypeError("runtime_client.invoke() returned invalid duration_ms payload")

        return CapabilityResult(
            status=status,
            output=payload.get("output"),
            error=payload.get("error") if isinstance(payload.get("error"), str) or payload.get("error") is None else str(payload.get("error")),
            error_code=payload.get("error_code")
            if isinstance(payload.get("error_code"), str) or payload.get("error_code") is None
            else str(payload.get("error_code")),
            report=payload.get("report"),
            node_report=node_report,
            artifacts=artifacts,
            duration_ms=float(duration_ms) if isinstance(duration_ms, (int, float)) else None,
            metadata=metadata,
        )

    def _capability_result_to_dict(self, result: CapabilityResult) -> dict[str, Any]:
        """把本地 CapabilityResult 收敛为 replay surface 的最小 dict。"""

        return {
            "status": result.status.value,
            "output": result.output,
            "error": result.error,
            "error_code": result.error_code,
            "artifacts": list(result.artifacts),
            "metadata": dict(result.metadata),
        }

    def _encode_rpc_stream_item(self, item: dict[str, Any] | str, *, use_sse: bool) -> str:
        """把 runtime client 的流式 item 统一 framing 为现有 JSONL/SSE 输出。"""

        if isinstance(item, str):
            if use_sse:
                return item if item.startswith("data: ") else f"data: {item.rstrip()}\n\n"
            return item if item.endswith("\n") else item + "\n"

        event = RuntimeEvent.model_validate(item)
        return encode_json_line(event, prefix_data=use_sse)

    async def _reap_handle_when_done(self, *, run_id: str, session: Any) -> None:
        wait_done = getattr(session, "wait_done", None)
        if not callable(wait_done):
            return
        await wait_done()
        self._handles.pop(run_id, None)


__all__ = [
    "RuntimeSession",
    "RuntimeServiceRequest",
    "RuntimeServiceHandle",
    "RuntimeServiceFacade",
    "build_session_context",
]
