"""Adapters：桥接上游与能力组织层。"""
from __future__ import annotations

# 已有桥接适配器（不修改）
# from .agently_backend import AgentlyChatBackend
# from .triggerflow_tool import ...

# 新增能力适配器
from .agent_adapter import AgentAdapter
from .skill_adapter import SkillAdapter
from .workflow_adapter import WorkflowAdapter

__all__ = [
    "AgentAdapter",
    "WorkflowAdapter",
    "SkillAdapter",
]
