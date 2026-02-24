"""
证据链辅助：把“system 策略注入摘要”写入 NodeReport.meta。

说明：
- Bridge core 不应理解 system 策略文本；这里仅写入最小披露摘要（sha256/bytes/policy_id）。
- 该 hook 不要求必须实现 BridgeHook 全量方法；Bridge 调用侧通过 getattr 探测并安全调用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict

from ..types import NodeResultV2


class SystemPromptEvidence(BaseModel):
    """
    system prompt 注入证据（最小披露）。

    字段对齐 `openspec/specs/evidence-chain/spec.md`：
    - system_prompt_injected
    - system_prompt_sha256
    - system_prompt_bytes
    - system_policy_id
    """

    model_config = ConfigDict(extra="forbid")

    system_prompt_injected: bool
    system_prompt_sha256: Optional[str] = None
    system_prompt_bytes: Optional[int] = None
    system_policy_id: Optional[str] = None


@dataclass(frozen=True)
class SystemPromptEvidenceHook:
    """
    BridgeHook（片段）：在返回结果前把 system prompt 摘要写入 NodeReport.meta。

    参数：
    - evidence：system prompt 注入证据摘要（不得包含明文）
    """

    evidence: SystemPromptEvidence

    def before_return_result(self, context: Dict[str, Any], node_result: NodeResultV2) -> None:
        """
        在 Bridge 返回 NodeResult 前写入证据链摘要。

        参数：
        - context：Bridge hook_context（脱敏摘要）
        - node_result：桥接层返回值
        """

        meta = node_result.node_report.meta
        meta.setdefault("system_prompt_injected", self.evidence.system_prompt_injected)
        if self.evidence.system_prompt_sha256 is not None:
            meta.setdefault("system_prompt_sha256", self.evidence.system_prompt_sha256)
        if self.evidence.system_prompt_bytes is not None:
            meta.setdefault("system_prompt_bytes", self.evidence.system_prompt_bytes)
        if self.evidence.system_policy_id is not None:
            meta.setdefault("system_policy_id", self.evidence.system_policy_id)
