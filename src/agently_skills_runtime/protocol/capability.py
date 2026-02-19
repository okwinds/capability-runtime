"""
protocol/capability.py

三种元能力（Skill / Agent / Workflow）共享的统一接口类型定义。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CapabilityKind(str, Enum):
    """能力类型枚举。"""

    SKILL = "skill"
    AGENT = "agent"
    WORKFLOW = "workflow"


@dataclass(frozen=True)
class CapabilityRef:
    """
    能力引用（在组合中引用另一个能力）。

    参数：
    - id：被引用能力的唯一 ID。
    - kind：可选；若提供，可用于在校验/诊断中增强可读性。
    """

    id: str
    kind: CapabilityKind | None = None


@dataclass(frozen=True)
class CapabilitySpec:
    """
    能力声明的公共字段（组合进具体 Spec：SkillSpec.base / AgentSpec.base / WorkflowSpec.base）。

    参数：
    - id：能力唯一标识。
    - kind：能力类型。
    - name：展示名。
    - description：描述（可空）。
    - version：版本号（默认 0.1.0；由宿主/发布流程决定升级策略）。
    - tags：标签列表。
    - metadata：可扩展元数据（必须可 JSON 序列化）。
    """

    id: str
    kind: CapabilityKind
    name: str
    description: str = ""
    version: str = "0.1.0"
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class CapabilityStatus(str, Enum):
    """能力执行状态枚举。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class CapabilityResult:
    """
    所有能力执行后统一返回结构。

    参数：
    - status：执行状态。
    - output：输出（类型由能力决定；可为 dict/str/任意 JSON 友好结构）。
    - error：错误摘要（失败时建议提供；不得包含敏感信息）。
    - report：可选执行报告对象（后续步骤扩展）。
    - artifacts：产物路径列表（相对/绝对由宿主约定；本层不强制）。
    """

    status: CapabilityStatus
    output: Any = None
    error: str | None = None
    report: Any | None = None
    artifacts: list[str] = field(default_factory=list)

