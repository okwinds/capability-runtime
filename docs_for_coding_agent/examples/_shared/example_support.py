from __future__ import annotations

"""
docs_for_coding_agent/examples 共享支持代码（面向编码智能体的可回归示例库）。

设计目标：
- 让每个示例都能在离线环境跑通（pytest 门禁）；
- 以最小代码演示 Runtime + skills_runtime 的“证据链”用法；
- 复用最少的 helper，避免示例之间复制粘贴导致漂移。
"""

import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from skills_runtime.safety.approvals import ApprovalDecision, ApprovalProvider, ApprovalRequest

from agently_skills_runtime import Runtime, RuntimeConfig


class ApproveAll(ApprovalProvider):
    """
    测试/示例用审批器：永远批准（避免离线示例阻塞）。

    注意：
    - 用于“离线门禁”时，这能确保示例稳定跑通；
    - 若你需要验证“审批证据链”，应在示例内断言 NodeReport.tool_calls[*].approval_decision。
    """

    async def request_approval(self, *, request: ApprovalRequest, timeout_ms: Optional[int] = None) -> ApprovalDecision:
        _ = (request, timeout_ms)
        return ApprovalDecision.APPROVED_FOR_SESSION


@dataclass(frozen=True)
class ExampleWorkspace:
    """示例工作区：统一放置 overlay 与 skills bundle。"""

    workspace_root: Path
    skills_root: Path
    overlay_path: Path


def write_filesystem_skills_bundle(*, workspace_root: Path, skills: Dict[str, str]) -> Path:
    """
    写入一个最小 filesystem skills bundle（每个 skill 一个目录 + SKILL.md）。

    参数：
    - workspace_root：工作区根目录
    - skills：skill_name -> SKILL.md body（不含 frontmatter 也可；会被写入）

    返回：
    - skills_root 路径
    """

    skills_root = workspace_root / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)
    for name, body in dict(skills).items():
        d = skills_root / str(name)
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(body, encoding="utf-8")
    return skills_root


def write_sdk_overlay_for_examples(
    *,
    workspace_root: Path,
    skills_root: Path,
    max_steps: int = 30,
    safety_mode: str = "ask",
    tool_allowlist: Optional[List[str]] = None,
    account: str = "examples",
    domain: str = "agent",
    namespace: Optional[str] = None,
    enable_references: bool = False,
    enable_actions: bool = False,
) -> Path:
    """
    写入一份最小 SDK overlay（runtime.yaml），用于离线示例回归。

    参数：
    - workspace_root：工作区根目录
    - skills_root：skills bundle 根目录
    - max_steps：run.max_steps
    - safety_mode：ask|allow|deny
    - tool_allowlist：低风险工具白名单（减少审批交互；示例一般仍使用 ask + 审批证据链）
    - account/domain：legacy skills space 字段（用于 `$[account:domain].skill`；必要时映射为 namespace）
    - namespace：v0.1.5+ skills space 字段（用于 `$[namespace].skill`；在 legacy 上游仅支持 2 段映射）
    - enable_references/actions：是否启用 skills 的 references/actions 扩展能力

    返回：
    - overlay_path（workspace_root/runtime.yaml）
    """

    allowlist = tool_allowlist or ["read_file", "grep_files", "list_dir", "file_read"]
    overlay_path = workspace_root / "runtime.yaml"

    from agently_skills_runtime.upstream_compat import (
        build_namespace_from_account_domain,
        detect_skills_space_schema,
        split_namespace_to_account_domain,
    )

    space_schema = detect_skills_space_schema()
    account_for_overlay = account
    domain_for_overlay = domain
    namespace_for_overlay = namespace
    if space_schema == "namespace":
        if namespace_for_overlay is None:
            namespace_for_overlay = build_namespace_from_account_domain(account=account_for_overlay, domain=domain_for_overlay)
    else:
        if namespace_for_overlay is not None:
            account_for_overlay, domain_for_overlay = split_namespace_to_account_domain(namespace_for_overlay)
            namespace_for_overlay = None

    space_lines = (
        f"                  namespace: {namespace_for_overlay!r}\n"
        if space_schema == "namespace"
        else f"                  account: {account_for_overlay!r}\n                  domain: {domain_for_overlay!r}\n"
    )
    overlay_path.write_text(
        textwrap.dedent(
            f"""\
            run:
              max_steps: {int(max_steps)}
            safety:
              mode: {safety_mode!r}
              approval_timeout_ms: 60000
              tool_allowlist:
            """
        )
        + "".join([f"    - {t!r}\n" for t in allowlist])
        + textwrap.dedent(
            f"""\
            sandbox:
              default_policy: none
            skills:
              strictness:
                unknown_mention: error
                duplicate_name: error
                mention_format: strict
              references:
                enabled: {str(bool(enable_references)).lower()}
              actions:
                enabled: {str(bool(enable_actions)).lower()}
              spaces:
                - id: example-space
{space_lines.rstrip()}
                  sources: [example-fs]
                  enabled: true
              sources:
                - id: example-fs
                  type: filesystem
                  options:
                    root: {str(skills_root.resolve())!r}
            """
        ),
        encoding="utf-8",
    )
    return overlay_path


def prepare_example_workspace(
    *,
    workspace_root: Path,
    skills: Dict[str, str],
    max_steps: int = 30,
    safety_mode: str = "ask",
    enable_references: bool = False,
    enable_actions: bool = False,
) -> ExampleWorkspace:
    """
    初始化示例工作区（skills bundle + overlay）。

    参数：
    - workspace_root：工作区根目录
    - skills：skill_name -> SKILL.md 内容
    - max_steps/safety_mode：overlay 参数

    返回：
    - ExampleWorkspace
    """

    workspace_root.mkdir(parents=True, exist_ok=True)
    skills_root = write_filesystem_skills_bundle(workspace_root=workspace_root, skills=skills)
    overlay_path = write_sdk_overlay_for_examples(
        workspace_root=workspace_root,
        skills_root=skills_root,
        max_steps=max_steps,
        safety_mode=safety_mode,
        enable_references=enable_references,
        enable_actions=enable_actions,
    )
    return ExampleWorkspace(workspace_root=workspace_root, skills_root=skills_root, overlay_path=overlay_path)


def build_offline_runtime(
    *,
    workspace_root: Path,
    overlay_path: Path,
    sdk_backend: Any,
    preflight_mode: str = "off",
    approval_provider: Optional[ApprovalProvider] = None,
    skills_config: Optional[Dict[str, Any]] = None,
    custom_tools: Optional[list[Any]] = None,
    exec_sessions: Any = None,
    collab_manager: Any = None,
    mode: str = "sdk_native",
) -> Runtime:
    """
    构造离线 Runtime（sdk_native/bridge 均可，默认 sdk_native）。

    参数：
    - workspace_root：工作区根目录
    - overlay_path：SDK overlay 路径
    - sdk_backend：注入的 ChatBackend（FakeChatBackend 等）
    - preflight_mode：off|warn|error
    - approval_provider：审批器（可选；默认为 ApproveAll）
    - custom_tools：RuntimeConfig.custom_tools（可选）
    - exec_sessions/collab_manager：上游 Phase5 能力注入点（示例用 stub）
    - mode：RuntimeConfig.mode（默认 sdk_native；无需 Agently）

    返回：
    - Runtime
    """

    cfg = RuntimeConfig(
        mode=mode,  # type: ignore[arg-type]
        workspace_root=workspace_root,
        sdk_config_paths=[overlay_path],
        preflight_mode=preflight_mode,  # type: ignore[arg-type]
        sdk_backend=sdk_backend,
        approval_provider=approval_provider or ApproveAll(),
        skills_config=skills_config,
        exec_sessions=exec_sessions,
        collab_manager=collab_manager,
        custom_tools=list(custom_tools or []),
    )
    return Runtime(cfg)
