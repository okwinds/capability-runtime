"""
protocol/agent.py

Agent 元能力声明（轻量 IO schema + skills/tools/collaboration/workflow capability refs）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .capability import CapabilityRef, CapabilitySpec


@dataclass(frozen=True)
class AgentIOSchema:
    """
    轻量 IO schema（不引入 pydantic，保持协议层零依赖）。

    参数：
    - fields：字段名 -> 类型名（字符串）。
    - required：必填字段名列表。
    """

    fields: dict[str, str] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentSpec:
    """
    Agent 声明。

    参数：
    - base：公共能力字段。
    - skills：装载的 Skill ID 列表（字符串 ID）。
    - tools：可用工具 ID 列表（具体由 adapter/宿主定义）。
    - collaborators：可协作的其他 Agent 引用。
    - callable_workflows：可调用的 Workflow 引用。
    - input_schema/output_schema：轻量 schema（可选）。
    - loop_compatible：是否可被循环调用（提示性质；执行策略由宿主决定）。
    - llm_config：可选 LLM 覆盖配置（由 adapter 解释）。
    """

    base: CapabilitySpec
    skills: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    collaborators: list[CapabilityRef] = field(default_factory=list)
    callable_workflows: list[CapabilityRef] = field(default_factory=list)
    input_schema: AgentIOSchema | None = None
    output_schema: AgentIOSchema | None = None
    loop_compatible: bool = False
    llm_config: dict[str, Any] | None = None

