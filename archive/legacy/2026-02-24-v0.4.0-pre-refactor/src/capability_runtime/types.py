"""
桥接层对外数据结构（NodeReport v2 / NodeResult）。

说明：
- NodeReport 是“控制面强结构”输出，供 TriggerFlow 做分支/审计/回归。
- NodeResult 是一次运行的对外返回值：final_output + node_report + events_path。

对齐规格：
- `docs/internal/specs/engineering-spec/02_Technical_Design/CONTRACTS.md`
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


NodeStatus = Literal["success", "failed", "incomplete", "needs_approval"]


class NodeToolCallReport(BaseModel):
    """
    NodeReport.tool_calls 的最小条目。

    字段说明：
    - `data`：优先放入“可机器消费”的结构化 data（来自 ToolResultPayload.data），避免塞 stdout/stderr。
    """

    model_config = ConfigDict(extra="forbid")

    call_id: str
    name: str
    requires_approval: bool = False

    approval_key: Optional[str] = None
    approval_decision: Optional[Literal["approved", "approved_for_session", "denied", "abort"]] = None
    approval_reason: Optional[str] = None

    ok: bool = False
    error_kind: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class NodeReportV2(BaseModel):
    """NodeReport v2（控制面强结构）。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_id: str = Field(default="capability-runtime.node_report.v2", alias="schema")
    status: NodeStatus
    reason: Optional[str] = None
    completion_reason: str = ""

    engine: Dict[str, Any] = Field(default_factory=dict)
    bridge: Dict[str, Any] = Field(default_factory=dict)

    run_id: str
    turn_id: Optional[str] = None
    events_path: Optional[str] = None

    activated_skills: List[str] = Field(default_factory=list)
    tool_calls: List[NodeToolCallReport] = Field(default_factory=list)
    artifacts: List[str] = Field(default_factory=list)

    meta: Dict[str, Any] = Field(default_factory=dict)


class NodeResultV2(BaseModel):
    """
    桥接层一次运行的返回值。

    字段：
    - final_output：面向用户的数据面输出（可能为自由文本）
    - node_report：控制面强结构（可编排、可审计）
    - events_path：SDK WAL（JSONL）路径（来源于 SDK，不得伪造）
    - artifacts：产物路径列表（Phase 2 可能为空，但字段必须保留）
    """

    model_config = ConfigDict(extra="forbid")

    final_output: str
    node_report: NodeReportV2
    events_path: Optional[str] = None
    artifacts: List[str] = Field(default_factory=list)
