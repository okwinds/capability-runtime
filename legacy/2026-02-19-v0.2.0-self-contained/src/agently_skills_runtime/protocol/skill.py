"""
protocol/skill.py

Skills 元能力声明（包含可选的调度规则）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .capability import CapabilityRef, CapabilitySpec


@dataclass(frozen=True)
class SkillDispatchRule:
    """
    调度规则：Skill 可通过规则主动调度其他能力。

    参数：
    - condition：触发条件（Phase 1：仅要求支持 context bag key 存在/为真）。
    - target：目标能力引用。
    - priority：优先级（默认 0；数值越大优先级越高）。
    - metadata：可扩展元数据。
    """

    condition: str
    target: CapabilityRef
    priority: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillSpec:
    """
    Skills 声明。

    参数：
    - base：公共能力字段。
    - source：内容来源（文件路径/内联文本/URI）。
    - source_type：file | inline | uri（默认 file）。
    - dispatch_rules：调度规则列表。
    - inject_to：声明自动注入到哪些 Agent（Agent ID 列表；是否强校验由运行时策略决定）。
    """

    base: CapabilitySpec
    source: str
    source_type: str = "file"
    dispatch_rules: list[SkillDispatchRule] = field(default_factory=list)
    inject_to: list[str] = field(default_factory=list)

