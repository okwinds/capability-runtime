"""
Resume / 续跑辅助工具（可选）。

定位：
- 提供“从 events.jsonl 回放得到的最小 resume 状态”的工具化入口；
- 默认用于摘要/诊断（例如：恢复 approvals cache、生成 resume summary）；
- 不强制把 WAL replay 作为下一轮 prompt 的唯一 history 真相源（真相源仍由宿主持久化的 TurnDelta 决定）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, List, Optional, Union

from pydantic import BaseModel, ConfigDict

from skills_runtime.core.contracts import AgentEvent
from skills_runtime.state.replay import ResumeReplayState, rebuild_resume_replay_state


def load_agent_events_from_locator(
    *,
    events_path: Union[Path, str],
    wal_backend: Any | None = None,
) -> List[AgentEvent]:
    """
    从 locator 加载 AgentEvent 列表（用于回放/诊断）。

    参数：
    - events_path：WAL 路径或 locator（本仓对外字段名为 `events_path`；上游 `skills-runtime-sdk>=1.0` 可能为 `wal_locator`）
    - wal_backend：可选 WAL backend；当 locator 为 `wal://...` 时必须提供

    返回：
    - AgentEvent 列表（按文件顺序）
    """

    loc = str(events_path)
    if loc.startswith("wal://"):
        if wal_backend is None:
            raise ValueError("wal_backend is required for wal locator")
        read_events = getattr(wal_backend, "read_events", None)
        if callable(read_events):
            return _coerce_agent_events(read_events(loc))
        read_text = getattr(wal_backend, "read_text", None)
        if callable(read_text):
            raw = read_text(loc)
            return _parse_agent_events_jsonl(raw)
        raise TypeError("wal_backend does not support wal locator reads")

    # best-effort：允许 filesystem locator 追加 `#run_id=...` 等片段；文件读取仅使用其路径部分。
    if "#" in loc:
        loc = loc.split("#", 1)[0]

    raw = Path(loc).read_text(encoding="utf-8")
    return _parse_agent_events_jsonl(raw)


def load_agent_events_from_jsonl(
    *,
    events_path: Union[Path, str],
    wal_backend: Any | None = None,
) -> List[AgentEvent]:
    """
    兼容别名：保留旧函数名，实际委托到 locator 读取逻辑。
    """

    return load_agent_events_from_locator(events_path=events_path, wal_backend=wal_backend)


class ResumeReplaySummary(BaseModel):
    """
    resume replay 的最小摘要（默认用于诊断/观测，不包含 tool 输出明文）。
    """

    model_config = ConfigDict(extra="forbid")

    events_count: int
    last_terminal_type: Optional[str] = None
    approvals: dict
    tool_calls: "ReplayToolCallDigest"


class ReplayToolCallDigest(BaseModel):
    """replay / resume 所需的最小 tool call 摘要。"""

    model_config = ConfigDict(extra="forbid")

    requested_count: int
    finished_count: int
    pending_count: int
    latest_pending_call_ids: list[str]
    latest_tool_calls: list[dict]


class HostResumeState(BaseModel):
    """
    宿主续跑状态摘要。

    字段说明：
    - `run_id`：本轮运行 ID
    - `approvals`：最小审批统计
    - `last_terminal_type`：最近终态事件类型
    - `waiting_approval_key`：尚未决议的审批键
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    approvals: dict
    last_terminal_type: Optional[str] = None
    waiting_approval_key: Optional[str] = None
    tool_calls: ReplayToolCallDigest


def build_resume_replay_summary(
    *,
    events: List[AgentEvent] | None = None,
    events_path: Union[Path, str, None] = None,
    wal_backend: Any | None = None,
) -> tuple[ResumeReplayState, ResumeReplaySummary]:
    """
    基于 events 回放得到 resume state，并生成诊断摘要。

    参数：
    - events：可选 AgentEvent 列表
    - events_path：可选 locator；当未直接提供 events 时用于加载事件
    - wal_backend：可选 WAL backend；当 events_path 为 `wal://...` 时透传给 locator 读取

    返回：
    - (ResumeReplayState, ResumeReplaySummary)
    """

    events = _resolve_agent_events(events=events, events_path=events_path, wal_backend=wal_backend)
    st = rebuild_resume_replay_state(events)
    tool_calls = _build_replay_tool_call_digest(events)

    last_terminal_type = None
    for ev in reversed(events):
        if ev.type in ("run_completed", "run_failed", "run_cancelled"):
            last_terminal_type = ev.type
            break

    summary = ResumeReplaySummary(
        events_count=len(events),
        last_terminal_type=last_terminal_type,
        approvals={
            "approved_for_session_keys_count": len(st.approved_for_session_keys),
            "denied_approvals_by_key_count": len(st.denied_approvals_by_key),
        },
        tool_calls=tool_calls,
    )
    return st, summary


def build_host_resume_state(
    *,
    events: List[AgentEvent] | None = None,
    events_path: Union[Path, str, None] = None,
    wal_backend: Any | None = None,
) -> HostResumeState:
    """
    基于 events 回放得到面向宿主的续跑状态。

    参数：
    - events：可选 AgentEvent 列表
    - events_path：可选 locator；当未直接提供 events 时用于加载事件
    - wal_backend：可选 WAL backend；当 events_path 为 `wal://...` 时透传给 locator 读取

    返回：
    - HostResumeState（不暴露 tool 输出明文）
    """

    events = _resolve_agent_events(events=events, events_path=events_path, wal_backend=wal_backend)
    st, summary = build_resume_replay_summary(events=events)
    requested_keys: List[str] = []
    resolved_keys: set[str] = set()
    run_id = ""

    for ev in events:
        if not run_id and isinstance(ev.run_id, str):
            run_id = ev.run_id
        approval_key = ev.payload.get("approval_key")
        if not isinstance(approval_key, str) or not approval_key.strip():
            continue
        approval_key = approval_key.strip()
        if ev.type == "approval_requested":
            requested_keys.append(approval_key)
        elif ev.type == "approval_decided":
            resolved_keys.add(approval_key)

    waiting_approval_key = None
    for approval_key in reversed(requested_keys):
        if approval_key not in resolved_keys:
            waiting_approval_key = approval_key
            break

    return HostResumeState(
        run_id=run_id,
        approvals={
            **summary.approvals,
            "pending_approval_keys_count": len([key for key in requested_keys if key not in resolved_keys]),
        },
        last_terminal_type=summary.last_terminal_type,
        waiting_approval_key=waiting_approval_key,
        tool_calls=summary.tool_calls,
    )


def _events_after_last_run_started(events: List[AgentEvent]) -> List[AgentEvent]:
    """只消费最近一次 run_started 之后的事件片段，与上游 replay 口径保持一致。"""

    last_idx = -1
    for i, ev in enumerate(events):
        if ev.type == "run_started":
            last_idx = i
    if last_idx < 0:
        return list(events)
    return list(events[last_idx + 1 :])


def _resolve_agent_events(
    *,
    events: List[AgentEvent] | None,
    events_path: Union[Path, str, None],
    wal_backend: Any | None,
) -> List[AgentEvent]:
    """统一解析 events / locator 两类输入。"""

    if events is not None:
        return list(events)
    if events_path is None:
        raise TypeError("either events or events_path is required")
    return load_agent_events_from_locator(events_path=events_path, wal_backend=wal_backend)


def _parse_agent_events_jsonl(raw: str) -> List[AgentEvent]:
    """把 JSONL 文本解析为 AgentEvent 列表。"""

    events: List[AgentEvent] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        obj = json.loads(s)
        events.append(AgentEvent.model_validate(obj))
    return events


def _coerce_agent_events(items: Iterable[Any]) -> List[AgentEvent]:
    """把 backend 返回的事件序列归一为 AgentEvent 列表。"""

    events: List[AgentEvent] = []
    for item in items:
        if isinstance(item, AgentEvent):
            events.append(item)
        else:
            events.append(AgentEvent.model_validate(item))
    return events


def _build_replay_tool_call_digest(events: List[AgentEvent]) -> ReplayToolCallDigest:
    """从事件流中提取 replay / resume 所需的最小 tool call 摘要。"""

    seg = _events_after_last_run_started(events)
    requested_count = 0
    finished_count = 0
    pending_ids: list[str] = []
    first_seen_order: list[str] = []
    calls_by_id: dict[str, dict] = {}

    for ev in seg:
        if ev.type == "tool_call_requested":
            call_id = str(ev.payload.get("call_id") or "").strip()
            name = str(ev.payload.get("name") or ev.payload.get("tool") or "").strip()
            if not call_id or not name:
                continue
            requested_count += 1
            if call_id not in first_seen_order:
                first_seen_order.append(call_id)
            if call_id not in pending_ids:
                pending_ids.append(call_id)
            calls_by_id[call_id] = {
                "call_id": call_id,
                "name": name,
                "step_id": str(ev.step_id or "").strip() or None,
                "status": "pending",
            }
            continue

        if ev.type == "tool_call_finished":
            call_id = str(ev.payload.get("call_id") or "").strip()
            name = str(ev.payload.get("tool") or ev.payload.get("name") or "").strip()
            if not call_id or not name:
                continue
            finished_count += 1
            if call_id not in first_seen_order:
                first_seen_order.append(call_id)
            if call_id in pending_ids:
                pending_ids.remove(call_id)
            prev = calls_by_id.get(call_id) or {}
            calls_by_id[call_id] = {
                "call_id": call_id,
                "name": name,
                "step_id": prev.get("step_id") or (str(ev.step_id or "").strip() or None),
                "status": "finished",
            }

    latest_ids = first_seen_order[-20:]
    latest_tool_calls = [calls_by_id[call_id] for call_id in latest_ids if call_id in calls_by_id]
    return ReplayToolCallDigest(
        requested_count=requested_count,
        finished_count=finished_count,
        pending_count=len(pending_ids),
        latest_pending_call_ids=list(pending_ids),
        latest_tool_calls=latest_tool_calls,
    )
