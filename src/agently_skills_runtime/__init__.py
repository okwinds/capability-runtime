"""
agently-skills-runtime

本包提供一个“桥接适配层”，把：
- 上游 Agently（TriggerFlow + provider 配置/网络传输层）
- 上游 skills-runtime-sdk-python（agent_sdk：skills/tools/approvals/WAL/事件）

组合成一个可在 TriggerFlow 节点内调用的生产级 runtime。

对齐规格入口：
- `docs/specs/engineering-spec/SPEC_INDEX.md`
"""

from .runtime import AgentlySkillsRuntime
from .types import NodeReportV2, NodeResultV2

__all__ = ["AgentlySkillsRuntime", "NodeReportV2", "NodeResultV2"]
