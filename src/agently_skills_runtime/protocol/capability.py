from __future__ import annotations

"""三种元能力共享的统一接口。"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class CapabilityKind(str, Enum):
    """能力种类。"""

    SKILL = "skill"
    AGENT = "agent"
    WORKFLOW = "workflow"


@dataclass(frozen=True)
class CapabilityRef:
    """
    能力引用——在组合中引用另一个能力。

    参数：
    - id: 被引用能力的唯一 ID
    - kind: 可选的类型提示（用于校验，不设则运行时从 Registry 推断）
    """

    id: str
    kind: Optional[CapabilityKind] = None


@dataclass(frozen=True)
class CapabilitySpec:
    """
    能力声明的公共字段。

    参数：
    - id: 全局唯一 ID（如 "MA-013"、"WF-001D"）
    - kind: 能力种类（skill/agent/workflow）
    - name: 人类可读名称（如 "单角色设计师"）
    - description: 描述（可为空）
    - version: 语义化版本（默认 "0.1.0"）
    - tags: 标签列表（用于分类和搜索）
    - metadata: 自由扩展字段（框架不解读，业务可用于存储额外信息）
    """

    id: str
    kind: CapabilityKind
    name: str
    description: str = ""
    version: str = "0.1.0"
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class CapabilityStatus(str, Enum):
    """能力执行状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class CapabilityResult:
    """
    所有能力执行后返回此结构。

    参数：
    - status: 执行状态
    - output: 执行输出（类型由具体能力决定，通常是 dict 或 str）
    - error: 错误信息（仅 FAILED 时非 None）
    - report: 执行报告（可选，通常是 NodeReport 或嵌套的子报告列表）
    - artifacts: 产出的文件路径列表
    - duration_ms: 执行耗时（毫秒，可选）
    - metadata: 扩展信息
    """

    status: CapabilityStatus
    output: Any = None
    error: Optional[str] = None
    report: Optional[Any] = None
    artifacts: List[str] = field(default_factory=list)
    duration_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
