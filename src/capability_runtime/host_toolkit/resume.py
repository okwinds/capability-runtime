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
from typing import List, Optional, Union

from pydantic import BaseModel, ConfigDict

from skills_runtime.core.contracts import AgentEvent
from skills_runtime.state.replay import ResumeReplayState, rebuild_resume_replay_state


def load_agent_events_from_jsonl(*, events_path: Union[Path, str]) -> List[AgentEvent]:
    """
    从 events.jsonl 加载 AgentEvent 列表（用于回放/诊断）。

    参数：
    - events_path：WAL 路径或 locator（本仓对外字段名为 `events_path`；上游 `skills-runtime-sdk>=1.0` 可能为 `wal_locator`）

    返回：
    - AgentEvent 列表（按文件顺序）
    """

    loc = str(events_path)
    # best-effort：允许 wal_locator 追加 `#run_id=...` 等片段；文件读取仅使用其路径部分。
    if "#" in loc:
        loc = loc.split("#", 1)[0]
    if loc.startswith("wal://"):
        raise ValueError(f"wal locator is not a filesystem path: {loc}")

    raw = Path(loc).read_text(encoding="utf-8")
    events: List[AgentEvent] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        obj = json.loads(s)
        events.append(AgentEvent.model_validate(obj))
    return events


class ResumeReplaySummary(BaseModel):
    """
    resume replay 的最小摘要（默认用于诊断/观测，不包含 tool 输出明文）。
    """

    model_config = ConfigDict(extra="forbid")

    events_count: int
    last_terminal_type: Optional[str] = None
    approvals: dict


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


def build_resume_replay_summary(*, events: List[AgentEvent]) -> tuple[ResumeReplayState, ResumeReplaySummary]:
    """
    基于 events 回放得到 resume state，并生成诊断摘要。

    参数：
    - events：AgentEvent 列表

    返回：
    - (ResumeReplayState, ResumeReplaySummary)
    """

    st = rebuild_resume_replay_state(events)

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
    )
    return st, summary


def build_host_resume_state(*, events: List[AgentEvent]) -> HostResumeState:
    """
    基于 events 回放得到面向宿主的续跑状态。

    参数：
    - events：AgentEvent 列表

    返回：
    - HostResumeState（不暴露 tool 输出明文）
    """

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
    )
