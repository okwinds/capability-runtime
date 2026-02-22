"""
Web 原型的对外数据结构（API contract）。

约束：
- 面向前端的 payload 必须脱敏（不落输入明文/不落 secrets）。
- 事件流统一为 RunEvent，便于前端以 SSE 消费。
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


RunMode = Literal["demo", "demo_rag_pre_run", "demo_rag_tool", "real"]
RunStatus = Literal["queued", "running", "waiting_approval", "completed", "failed"]


class RunEvent(BaseModel):
    """SSE 事件条目（统一协议）。"""

    model_config = ConfigDict(extra="forbid")

    ts: str
    run_id: str
    type: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class StartSkillTaskRequest(BaseModel):
    """发起一次 skills runtime 运行。"""

    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1)
    mode: RunMode = "demo"


class StartFlowRequest(BaseModel):
    """发起一次 flow 运行（直接调用 runner；用于验证 runner 注入与输出形态）。"""

    model_config = ConfigDict(extra="forbid")

    flow_name: str = Field(min_length=1)
    input: Any = None
    timeout_sec: Optional[float] = None
    wait_for_result: bool = True


class StartRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str


class RunSnapshot(BaseModel):
    """run 的可轮询状态（结束后包含 NodeReport 与 events_path）。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: RunStatus
    final_output: str = ""
    node_report: Optional[Dict[str, Any]] = None
    events_path: Optional[str] = None
    error: Optional[str] = None


class ApprovalPendingItem(BaseModel):
    """待审批条目（脱敏）。"""

    model_config = ConfigDict(extra="forbid")

    approval_id: str
    run_id: str
    call_id: str
    question: str
    choices: list[str]
    context: Dict[str, Any] = Field(default_factory=dict)


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "deny"]
    reason: str = ""
