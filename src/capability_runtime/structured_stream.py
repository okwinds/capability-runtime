from __future__ import annotations

"""结构化流式消费的公开事件模型。"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class StructuredStreamEvent:
    """业务友好的低噪音结构化流事件。"""

    type: str
    run_id: str
    capability_id: str
    text: Optional[str] = None
    field: Optional[str] = None
    value: Any = None
    snapshot: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    output: Optional[Dict[str, Any]] = None
    raw_output: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None


def diff_top_level_fields(
    previous: Optional[Dict[str, Any]],
    current: Dict[str, Any],
) -> List[Tuple[str, Any]]:
    """计算顶层字段差异；仅输出新增或值发生变化的字段。"""

    previous = dict(previous or {})
    changed: List[Tuple[str, Any]] = []
    for key in current.keys():
        if previous.get(key) != current.get(key):
            changed.append((key, current.get(key)))
    return changed
