from __future__ import annotations

"""
Runtime UI Events v1（协议模型）。

定位：
- UI events 是“可观测/产品化投影层”，不是审计真相源；
- 真相源仍为 WAL/events/tool evidence → NodeReport；
- 本模块仅定义 v1 的稳定信封字段与最小结构约束。
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class StreamLevel(str, Enum):
    """事件输出层级。"""

    LITE = "lite"
    UI = "ui"
    RAW = "raw"


class PathSegment(BaseModel):
    """PathSegment（图投影路径段）。"""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1)
    id: str = Field(min_length=1)
    # v1 加法演进：用于多实例/嵌套消歧与展示（不要求每条事件都提供）
    instance_id: Optional[str] = None
    # `ref` 用于携带“逻辑身份”（例如 workflow spec id / capability id / tool name），避免 id 变为 opaque 后 UI 无法展示。
    # 约束：保持通用性，只提供 kind/id 两个维度。
    ref: Optional[Dict[str, str]] = None


class Evidence(BaseModel):
    """证据指针：用于回到 WAL/NodeReport/tool evidence 真相源。"""

    model_config = ConfigDict(extra="forbid")

    events_path: Optional[str] = None
    call_id: Optional[str] = None
    artifact_path: Optional[str] = None
    node_report_schema: Optional[str] = None


class RuntimeEvent(BaseModel):
    """
    RuntimeEvent v1：统一事件信封（Envelope）。

    约束：
    - `schema` 固定为 `agently-skills-runtime.runtime_event.v1`
    - `seq` 在单 run 内单调递增
    - `rid` 为传输层游标（续传用），可与 `seq` 等价但语义不同
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_id: str = Field(min_length=1, alias="schema")
    type: str = Field(min_length=1)
    run_id: str = Field(min_length=1)

    seq: int = Field(ge=0)
    ts_ms: int = Field(ge=0)
    level: StreamLevel

    path: List[PathSegment] = Field(default_factory=list)
    data: Dict[str, Any] = Field(default_factory=dict)

    rid: Optional[str] = None
    evidence: Optional[Evidence] = None
