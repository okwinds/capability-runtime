"""
protocol/workflow.py

Workflow 元能力声明（确定性编排：Step / Loop / Parallel / Conditional）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Union

from .capability import CapabilityRef, CapabilitySpec


@dataclass(frozen=True)
class InputMapping:
    """
    输入映射。

    参数：
    - source：来源表达式，支持：
      - "context.{key}"：从 ExecutionContext.bag 获取
      - "previous.{key}"：从上一步输出获取
      - "step.{step_id}.{key}"：从指定步骤输出获取
      - "literal.{value}"：字面量
      - "item" / "item.{key}"：循环中当前元素
    - target_field：目标字段名（写入 capability input dict）。
    """

    source: str
    target_field: str


@dataclass(frozen=True)
class Step:
    """基础步骤：执行单个能力。"""

    id: str
    capability: CapabilityRef
    input_mappings: list[InputMapping] = field(default_factory=list)


@dataclass(frozen=True)
class LoopStep:
    """
    循环步骤：对集合中每个元素执行能力。

    参数：
    - iterate_over：映射表达式，解析得到集合。
    - item_input_mappings：对每个 item 生成 capability input 的映射。
    - max_iterations：步骤级上限（默认 100）。
    - collect_as：结果收集字段名（默认 "results"）。
    """

    id: str
    capability: CapabilityRef
    iterate_over: str
    item_input_mappings: list[InputMapping] = field(default_factory=list)
    max_iterations: int = 100
    collect_as: str = "results"


@dataclass(frozen=True)
class ParallelStep:
    """
    并行步骤：同时执行多个分支能力（分支仅允许 Step/LoopStep）。

    参数：
    - branches：分支列表。
    - join_strategy：all_success | any_success | best_effort（默认 all_success）。
    """

    id: str
    branches: list[Union[Step, LoopStep]] = field(default_factory=list)
    join_strategy: str = "all_success"


@dataclass(frozen=True)
class ConditionalStep:
    """
    条件步骤：根据条件选择执行路径（分支仅允许 Step/LoopStep）。

    参数：
    - condition_source：条件来源表达式（由 ExecutionContext.resolve_mapping 解析）。
    - branches：key->分支（key 与解析值做字符串比较）。
    - default：默认分支（可选）。
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
    - base：公共能力字段。
    - steps：步骤列表（可混合 Step/Loop/Parallel/Conditional）。
    - context_schema：可选（提示性质；由宿主/adapter 决定是否校验）。
    - output_mappings：最终输出映射列表。
    """

    base: CapabilitySpec
    steps: list[WorkflowStep] = field(default_factory=list)
    context_schema: dict[str, str] | None = None
    output_mappings: list[InputMapping] = field(default_factory=list)

