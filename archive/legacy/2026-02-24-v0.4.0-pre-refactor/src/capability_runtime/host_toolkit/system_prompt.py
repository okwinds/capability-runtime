"""
system/developer 提示词（策略层）工具。

MVR 约束：
- system/developer 提示词不通过 `initial_history` 注入；
- 由宿主生成 SDK overlays（prompt/config）并注入到 `agent_sdk.Agent`（或通过 Bridge 透传 config_paths）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class SystemPrompt(BaseModel):
    """
    system/developer 提示词集合。

    字段：
    - system_text：system 提示词（可为空）
    - developer_text：developer 提示词（可为空）
    - policy_id：策略 ID/版本（可选；用于审计与回归追溯）
    """

    model_config = ConfigDict(extra="forbid")

    system_text: Optional[str] = None
    developer_text: Optional[str] = None
    policy_id: Optional[str] = None


class SystemPromptDigest(BaseModel):
    """
    system 提示词注入摘要（最小披露）。

    注意：该对象不得包含提示词明文。
    """

    model_config = ConfigDict(extra="forbid")

    injected: bool
    sha256: Optional[str] = None
    bytes: Optional[int] = None
    policy_id: Optional[str] = None


@runtime_checkable
class SystemPromptProvider(Protocol):
    """
    SystemPromptProvider：由宿主提供/实现。

    说明：
    - 框架不规定 system/developer 提示词从哪里来（文件/DB/规则引擎/租户配置）。
    - 该 provider 只返回“策略文本”，实际注入由调用方通过 overlays 完成。
    """

    def get_system_prompt(self, *, context: Dict[str, Any]) -> SystemPrompt:
        """
        读取/生成 system 提示词。

        参数：
        - context：宿主上下文（例如 tenant/user/session_id 等），由宿主定义

        返回：
        - SystemPrompt（可能为空）
        """

        ...


@dataclass(frozen=True)
class StaticSystemPromptProvider:
    """最小默认实现：返回固定的 SystemPrompt（便于测试与示例）。"""

    prompt: SystemPrompt

    def get_system_prompt(self, *, context: Dict[str, Any]) -> SystemPrompt:
        """忽略上下文，返回固定 prompt。"""

        return self.prompt


def build_prompt_overlay(*, prompt: SystemPrompt) -> Dict[str, Any]:
    """
    把 SystemPrompt 转成 agent_sdk 配置 overlays（prompt.*）。

    参数：
    - prompt：SystemPrompt

    返回：
    - overlays dict（可写入 YAML 并作为 config_paths 传入）
    """

    return {
        "prompt": {
            "system_text": prompt.system_text,
            "developer_text": prompt.developer_text,
        }
    }


def compute_system_prompt_digest(*, prompt: SystemPrompt) -> SystemPromptDigest:
    """
    计算 system prompt 摘要（sha256/bytes/policy_id），用于 NodeReport.meta。

    参数：
    - prompt：SystemPrompt（可能为空）

    返回：
    - SystemPromptDigest（不含明文）
    """

    injected = bool((prompt.system_text or "").strip() or (prompt.developer_text or "").strip())
    if not injected:
        return SystemPromptDigest(injected=False, sha256=None, bytes=0, policy_id=prompt.policy_id)

    canonical = {
        "system_text": prompt.system_text or "",
        "developer_text": prompt.developer_text or "",
        "policy_id": prompt.policy_id,
    }
    raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return SystemPromptDigest(
        injected=True,
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
        policy_id=prompt.policy_id,
    )

