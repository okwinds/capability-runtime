"""
Host toolkit（宿主工具箱）。

定位：
- 本包用于帮助宿主（Host）以“业务主控（真相源）+ 框架提供工具”的方式落地单智能体 session/turn 生命周期。
- 本包不实现业务存储/权限/审批 UI；仅提供可复用的模型、组装器与证据链辅助。

注意：
- system/developer 提示词在 MVR 中不通过 `initial_history` 注入，而通过 SDK prompt/config overlays 注入（见 `system_prompt`）。
"""

from .approvals_profiles import ApprovalsProfile, ApprovalsProfiles, validate_approvals_profile
from .evidence_hooks import SystemPromptEvidence, SystemPromptEvidenceHook
from .history import HistoryAssembler, HistoryAssemblerConfig
from .invoke_capability import InvokeCapabilityAllowlist, make_invoke_capability_tool
from .resume import ResumeReplaySummary, build_resume_replay_summary, load_agent_events_from_jsonl
from .system_prompt import (
    StaticSystemPromptProvider,
    SystemPrompt,
    SystemPromptDigest,
    SystemPromptProvider,
    build_prompt_overlay,
    compute_system_prompt_digest,
)
from .turn_delta import TurnDelta, TurnDeltaRedactor, TruncatingTurnDeltaRedactor

__all__ = [
    "ApprovalsProfile",
    "ApprovalsProfiles",
    "validate_approvals_profile",
    "SystemPromptEvidence",
    "SystemPromptEvidenceHook",
    "HistoryAssembler",
    "HistoryAssemblerConfig",
    "InvokeCapabilityAllowlist",
    "make_invoke_capability_tool",
    "ResumeReplaySummary",
    "build_resume_replay_summary",
    "load_agent_events_from_jsonl",
    "StaticSystemPromptProvider",
    "SystemPrompt",
    "SystemPromptDigest",
    "SystemPromptProvider",
    "build_prompt_overlay",
    "compute_system_prompt_digest",
    "TurnDelta",
    "TurnDeltaRedactor",
    "TruncatingTurnDeltaRedactor",
]
