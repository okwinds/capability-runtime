from __future__ import annotations

"""Agent 元能力声明。"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .capability import CapabilityRef, CapabilitySpec


@dataclass(frozen=True)
class AgentIOSchema:
    """
    轻量 IO schema——描述 Agent 的输入/输出字段。

    参数：
    - fields: 字段名 → 类型描述（如 {"synopsis": "str", "score": "int"}）
    - required: 必填字段列表
    """

    fields: Dict[str, str] = field(default_factory=dict)
    required: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentSpec:
    """
    Agent 声明。

    参数：
    - base: 公共能力字段
    - tools: 注册的 Tool 名称列表
    - collaborators: 可协作的其他 Agent 引用
    - callable_workflows: 可调用的 Workflow 引用
    - input_schema: 输入 schema（可选）
    - output_schema: 输出 schema（可选）
    - loop_compatible: 是否可被 LoopStep 循环调用
    - llm_config: LLM 覆盖配置
    - prompt_template: 可选的 prompt 模板（支持 {field} 占位符）
    - system_prompt: 可选的 system prompt
    """

    base: CapabilitySpec
    tools: List[str] = field(default_factory=list)
    collaborators: List[CapabilityRef] = field(default_factory=list)
    callable_workflows: List[CapabilityRef] = field(default_factory=list)
    input_schema: Optional[AgentIOSchema] = None
    output_schema: Optional[AgentIOSchema] = None
    loop_compatible: bool = False
    llm_config: Optional[Dict[str, Any]] = None
    prompt_template: Optional[str] = None
    system_prompt: Optional[str] = None
