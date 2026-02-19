from __future__ import annotations

"""Workflow 元能力声明。"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

from .capability import CapabilityRef, CapabilitySpec


@dataclass(frozen=True)
class InputMapping:
    """
    输入映射——定义步骤输入字段的数据来源。

    参数：
    - source: 数据源表达式
    - target_field: 目标输入字段名
    """

    source: str
    target_field: str


@dataclass(frozen=True)
class Step:
    """
    基础步骤——执行单个能力。

    参数：
    - id: 步骤 ID（在 Workflow 内唯一）
    - capability: 要调用的能力引用
    - input_mappings: 输入映射列表
    """

    id: str
    capability: CapabilityRef
    input_mappings: List[InputMapping] = field(default_factory=list)


@dataclass(frozen=True)
class LoopStep:
    """
    循环步骤——对集合中每个元素执行能力。

    参数：
    - id: 步骤 ID
    - capability: 每次循环调用的能力引用
    - iterate_over: 数据源表达式（解析后应为 List）
    - item_input_mappings: 循环内的输入映射（可用 "item"/"item.{key}" 前缀）
    - max_iterations: 单步最大循环次数
    - collect_as: 结果收集字段名
    - fail_strategy: "abort" | "skip" | "collect"
    """

    id: str
    capability: CapabilityRef
    iterate_over: str
    item_input_mappings: List[InputMapping] = field(default_factory=list)
    max_iterations: int = 100
    collect_as: str = "results"
    fail_strategy: str = "abort"


@dataclass(frozen=True)
class ParallelStep:
    """
    并行步骤——同时执行多个能力。

    参数：
    - id: 步骤 ID
    - branches: 并行执行的步骤列表
    - join_strategy: "all_success" | "any_success" | "best_effort"
    """

    id: str
    branches: List[Union[Step, LoopStep]] = field(default_factory=list)
    join_strategy: str = "all_success"


@dataclass(frozen=True)
class ConditionalStep:
    """
    条件步骤——根据条件选择执行路径。

    参数：
    - id: 步骤 ID
    - condition_source: 条件值的数据源表达式
    - branches: 条件值 → 步骤的映射
    - default: 无匹配时的默认步骤
    """

    id: str
    condition_source: str
    branches: Dict[str, Union[Step, LoopStep]] = field(default_factory=dict)
    default: Optional[Union[Step, LoopStep]] = None


WorkflowStep = Union[Step, LoopStep, ParallelStep, ConditionalStep]


@dataclass(frozen=True)
class WorkflowSpec:
    """
    Workflow 声明。

    参数：
    - base: 公共能力字段
    - steps: 步骤列表（按声明顺序执行，ParallelStep 内部并行）
    - context_schema: 初始 context bag 的 schema（可选）
    - output_mappings: 输出映射（从 context/step_outputs 构造最终输出）
    """

    base: CapabilitySpec
    steps: List[WorkflowStep] = field(default_factory=list)
    context_schema: Optional[Dict[str, str]] = None
    output_mappings: List[InputMapping] = field(default_factory=list)
