from __future__ import annotations

"""Skills 元能力声明。"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .capability import CapabilityRef, CapabilitySpec


@dataclass(frozen=True)
class SkillDispatchRule:
    """
    调度规则——Skill 可通过规则主动调度其他能力。

    参数：
    - condition: 触发条件表达式（Phase 1 支持简单的 context bag key 存在性检查）
    - target: 目标能力引用
    - priority: 优先级（数值越大越优先，同优先级按声明顺序）
    - metadata: 扩展信息
    """

    condition: str
    target: CapabilityRef
    priority: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillSpec:
    """
    Skills 声明。

    参数：
    - base: 公共能力字段
    - source: Skill 内容来源
      · source_type="file" 时：文件路径（相对于 workspace_root）
      · source_type="inline" 时：直接包含的文本内容
      · source_type="uri" 时：资源 URI（默认禁用，需 allowlist 授权）
    - source_type: "file" | "inline" | "uri"（默认 "file"）
    - dispatch_rules: 调度规则列表
    - inject_to: 声明自动注入到哪些 Agent（Agent ID 列表）
    """

    base: CapabilitySpec
    source: str
    source_type: str = "file"
    dispatch_rules: List[SkillDispatchRule] = field(default_factory=list)
    inject_to: List[str] = field(default_factory=list)
