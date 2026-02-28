from __future__ import annotations

"""
examples/apps 共享支持代码（面向人类的应用示例）。

目标：
- 每个 app 示例都像“小应用/MVP”：有过程感、有产物、有证据链；
- 支持双模式：
  - offline：离线可回归（FakeChatBackend 驱动真实 skills_runtime.Agent loop）
  - real：真模型可跑（OpenAI-compatible，通过 Agently requester 作为传输层）
- skills-first：通过严格 mention token 触发 skills 注入（Scheme2：薄壳 Agent 节点承载 skills）。
"""

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from skills_runtime.core.contracts import AgentEvent
from skills_runtime.safety.approvals import ApprovalDecision, ApprovalProvider, ApprovalRequest
from skills_runtime.tools.protocol import HumanIOProvider

from capability_runtime import Runtime, RuntimeConfig


def detect_skills_space_schema() -> str:
    """
    探测当前安装的 skills-runtime-sdk 期望的 skills.spaces schema。

    返回：
    - "namespace"：上游要求 `skills.spaces[].namespace`
    - "account_domain"：上游要求 `skills.spaces[].account` + `domain`
    """

    try:
        import skills_runtime.config.loader as loader

        space = getattr(getattr(loader, "AgentSdkSkillsConfig", None), "Space", None)
        if space is not None:
            fields = getattr(space, "model_fields", None)
            if isinstance(fields, dict) and "namespace" in fields:
                return "namespace"
    except Exception:
        return "account_domain"

    try:
        import skills_runtime.skills.mentions as mentions

        if hasattr(mentions, "is_valid_namespace"):
            return "namespace"
    except Exception:
        return "account_domain"

    return "account_domain"


def _build_namespace_from_account_domain(*, account: str, domain: str) -> str:
    """将 legacy account/domain 映射为两段 namespace（`account:domain`）。"""

    return f"{str(account).strip()}:{str(domain).strip()}"


def _split_namespace_to_account_domain(namespace: str) -> Tuple[str, str]:
    """
    将两段 namespace 映射回 legacy account/domain（仅当恰好 2 段时允许）。

    异常：
    - ValueError：namespace 不是 2 段时（无法无损映射）
    """

    raw = str(namespace).strip()
    parts = [p for p in raw.split(":") if p]
    if len(parts) != 2:
        raise ValueError("namespace must have exactly 2 segments to map into legacy account/domain")
    return parts[0], parts[1]


def env_or_default(name: str, default: str) -> str:
    """
    读取环境变量（不存在则返回 default）。

    参数：
    - name：环境变量名
    - default：默认值

    返回：
    - 读取到的字符串值（去掉首尾空格）
    """

    v = str(os.environ.get(name, "")).strip()
    return v if v else default


def load_env_file(dotenv_path: Path) -> None:
    """
    读取 `.env` 并写入进程环境（不覆盖已有值）。

    参数：
    - dotenv_path：.env 文件路径
    """

    for raw in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def write_overlay_for_app(
    *,
    workspace_root: Path,
    skills_root: Path,
    max_steps: int,
    safety_mode: str = "ask",
    tool_allowlist: Optional[List[str]] = None,
    account: str = "examples",
    domain: str = "app",
    namespace: Optional[str] = None,
    enable_references: bool = False,
    enable_actions: bool = False,
    planner_model: Optional[str] = None,
    executor_model: Optional[str] = None,
) -> Path:
    """
    为单个 app 写入 SDK overlay（runtime.yaml）。

    参数：
    - workspace_root：工作区根目录（WAL/产物落盘位置）
    - skills_root：skills bundle 根目录（filesystem source root）
    - max_steps：run.max_steps（防止 loop 失控）
    - safety_mode：ask|allow|deny
    - tool_allowlist：低风险工具白名单（减少交互成本）
    - account/domain：legacy skills space 字段（用于 `$[account:domain].skill`；会在需要时映射到 namespace）
    - namespace：v0.1.5+ skills space 字段（用于 `$[namespace].skill`；当运行在 legacy 上游时仅支持 2 段映射）
    - enable_references/actions：是否启用 skill_ref_read/skill_exec（默认禁用）
    - planner_model/executor_model：可选模型名（真实模式推荐显式设置；离线可忽略）

    返回：
    - overlay 文件路径
    """

    overlay = workspace_root / "runtime.yaml"
    # 默认 allowlist 选择“可显著改善示例 UX 的低风险工具”：
    # - read_file/grep/list_dir/file_read：只读
    # - update_plan：只影响运行期 UI/进度展示
    # - file_write：只写 workspace（示例契约要求产物落盘；避免每次都审批导致体验碎片化）
    allowlist = tool_allowlist or ["read_file", "grep_files", "list_dir", "file_read", "update_plan", "file_write"]

    space_schema = detect_skills_space_schema()
    account_for_overlay = account
    domain_for_overlay = domain
    namespace_for_overlay = namespace
    if space_schema == "namespace":
        if namespace_for_overlay is None:
            namespace_for_overlay = _build_namespace_from_account_domain(account=account_for_overlay, domain=domain_for_overlay)
    else:
        if namespace_for_overlay is not None:
            account_for_overlay, domain_for_overlay = _split_namespace_to_account_domain(namespace_for_overlay)
            namespace_for_overlay = None

    lines: List[str] = []
    lines.extend(
        [
            "run:",
            f"  max_steps: {int(max_steps)}",
            "safety:",
            f"  mode: {safety_mode!r}",
            "  approval_timeout_ms: 60000",
            "  tool_allowlist:",
        ]
    )
    for tool in allowlist:
        lines.append(f"    - {str(tool)!r}")

    lines.extend(
        [
            "sandbox:",
            "  default_policy: none",
            "skills:",
            "  strictness:",
            "    unknown_mention: error",
            "    duplicate_name: error",
            "    mention_format: strict",
            "  references:",
            f"    enabled: {str(bool(enable_references)).lower()}",
            "  actions:",
            f"    enabled: {str(bool(enable_actions)).lower()}",
            "  spaces:",
            "    - id: app-space",
            *(  # skills-runtime-sdk v0.1.5+
                [f"      namespace: {str(namespace_for_overlay)!r}"]
                if space_schema == "namespace"
                else [f"      account: {str(account_for_overlay)!r}", f"      domain: {str(domain_for_overlay)!r}"]
            ),
            "      sources: [app-fs]",
            "      enabled: true",
            "  sources:",
            "    - id: app-fs",
            "      type: filesystem",
            "      options:",
            f"        root: {str(skills_root.resolve())!r}",
        ]
    )

    if planner_model is not None or executor_model is not None:
        lines.append("models:")
        if planner_model is not None:
            lines.append(f"  planner: {str(planner_model)!r}")
        if executor_model is not None:
            lines.append(f"  executor: {str(executor_model)!r}")

    overlay.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return overlay


class ScriptedApprovalProvider(ApprovalProvider):
    """
    离线回归用审批器：按次数返回预置审批决策。

    约束：
    - decisions 用尽后默认拒绝（fail-closed），暴露测试/示例配置问题。
    """

    def __init__(self, decisions: List[ApprovalDecision]) -> None:
        self._decisions = list(decisions)
        self.calls: List[ApprovalRequest] = []

    async def request_approval(self, *, request: ApprovalRequest, timeout_ms: Optional[int] = None) -> ApprovalDecision:
        _ = timeout_ms
        self.calls.append(request)
        if self._decisions:
            return self._decisions.pop(0)
        return ApprovalDecision.DENIED


class TerminalApprovalProvider(ApprovalProvider):
    """
    终端交互式审批（最小 UX）。

    约束：
    - 默认 fail-closed（用户未明确输入 y/Y 则拒绝）。
    """

    async def request_approval(self, *, request: ApprovalRequest, timeout_ms: Optional[int] = None) -> ApprovalDecision:
        _ = timeout_ms
        print("\n[approval] 需要审批：")
        print(f"- tool: {request.tool}")
        print(f"- summary: {request.summary}")
        if request.details:
            print(f"- details: {request.details}")
        raw = input("[approval] 允许执行？(y/N)：").strip().lower()
        if raw in {"y", "yes"}:
            return ApprovalDecision.APPROVED_FOR_SESSION
        return ApprovalDecision.DENIED


class AutoApprovalProvider(ApprovalProvider):
    """
    自动审批器（非交互 smoke / 服务端示例用）。

    适用场景：
    - `--non-interactive`：用于真实模型 smoke，避免卡在 approvals；
    - HTTP/SSE 服务：服务端无法在终端交互批准。

    安全边界：
    - 该审批器仅用于 examples/apps；生产默认不应启用“全放行”。
    """

    def __init__(self) -> None:
        self.calls: List[ApprovalRequest] = []

    async def request_approval(self, *, request: ApprovalRequest, timeout_ms: Optional[int] = None) -> ApprovalDecision:
        _ = timeout_ms
        self.calls.append(request)
        return ApprovalDecision.APPROVED_FOR_SESSION


class ScriptedHumanIO(HumanIOProvider):
    """
    预置 HumanIOProvider：按 question_id 返回预置答案。

    说明：
    - offline 回归与 real smoke 都可以使用（避免交互阻塞）；
    - 对未知 question_id 默认返回空串（可选配置 default_answer）。
    """

    def __init__(self, answers_by_question_id: Dict[str, str], *, default_answer: str = "") -> None:
        self._answers = dict(answers_by_question_id)
        self._default = str(default_answer)

    def request_human_input(
        self,
        *,
        call_id: str,
        question: str,
        choices: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        timeout_ms: Optional[int] = None,
    ) -> str:
        _ = (question, choices, context, timeout_ms)
        qid = str(call_id).split(":")[-1]
        if qid in self._answers:
            return str(self._answers[qid])
        return self._default


class TerminalHumanIO(HumanIOProvider):
    """终端交互式 HumanIOProvider（最小 UX）。"""

    def request_human_input(
        self,
        *,
        call_id: str,
        question: str,
        choices: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        timeout_ms: Optional[int] = None,
    ) -> str:
        _ = (call_id, timeout_ms)
        header = str((context or {}).get("header") or "")
        if header:
            print(f"\n[question] {header}")
        print(f"[question] {question}")
        if choices:
            print("[choices]")
            for idx, c in enumerate(list(choices), start=1):
                print(f"  {idx}. {c}")
            print("[hint] 可输入选项文本，或直接输入自定义值。")
        return input("[answer] ").strip()


def missing_artifacts(*, workspace_root: Path, required: List[str]) -> List[str]:
    """
    检查 workspace 是否缺失必需产物。

    参数：
    - workspace_root：工作区根目录
    - required：必需文件相对路径列表（相对 workspace_root）

    返回：
    - 缺失文件列表（空列表表示全部存在）
    """

    missing: List[str] = []
    for rel in required:
        p = (workspace_root / rel).resolve()
        if not p.exists():
            missing.append(rel)
    return missing


def stream_runtime_with_min_ux(
    *,
    runtime: Runtime,
    capability_id: str,
    input: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Optional[str]]:
    """
    运行 `Runtime.run_stream` 并打印最小过程 UX。

    参数：
    - runtime：本仓 Runtime
    - capability_id：能力 ID（Agent/Workflow）
    - input：输入 dict

    返回：
    - (final_output, wal_locator)
    """

    final_output = ""
    wal_locator: Optional[str] = None
    t0 = time.monotonic()

    async def _run() -> Tuple[str, Optional[str]]:
        nonlocal final_output, wal_locator
        async for item in runtime.run_stream(capability_id, input=input or {}):
            if isinstance(item, AgentEvent):
                if item.type in {
                    "run_started",
                    "run_completed",
                    "skill_injected",
                    "plan_updated",
                    "approval_requested",
                    "approval_decided",
                }:
                    print(f"[event] {item.type}")
                if item.type == "tool_call_started":
                    tool = str((item.payload or {}).get("tool") or "")
                    print(f"[tool] start {tool}")
                if item.type == "tool_call_finished":
                    tool = str((item.payload or {}).get("tool") or "")
                    ok = (item.payload or {}).get("result", {}).get("ok") if isinstance(item.payload, dict) else None
                    print(f"[tool] done {tool} ok={ok}")
            elif isinstance(item, dict):
                typ = str(item.get("type") or "")
                if typ.startswith("workflow."):
                    step_id = str(item.get("step_id") or "")
                    suffix = f" step_id={step_id}" if step_id else ""
                    print(f"[event] {typ}{suffix}")
                    continue
                # 非 workflow 事件：保持 best-effort 展示，避免误判为终态结果。
                if typ:
                    print(f"[event] {typ}")
                    continue
                # 未知 dict：不应落入终态解析（避免 AttributeError）
                print("[event] dict")
                continue
            else:
                final_output = str(item.output or "")
                wal_locator = str(item.node_report.events_path) if item.node_report and item.node_report.events_path else None
        dt_ms = int((time.monotonic() - t0) * 1000)
        print(f"[done] wall_time_ms={dt_ms}")
        print(f"[done] wal_locator={wal_locator}")
        return final_output, wal_locator

    import asyncio

    return asyncio.run(_run())


def build_bridge_runtime_from_env(
    *,
    workspace_root: Path,
    overlay: Path,
    approval_provider: Optional[ApprovalProvider],
    human_io: Optional[HumanIOProvider],
    sdk_backend: Any = None,
    output_validation_mode: str = "off",
    output_validator: Optional[Callable[..., Any]] = None,
) -> Runtime:
    """
    基于 `.env`（OpenAI-compatible）构造 bridge Runtime（真实模式），或注入 Fake backend（离线）。

    参数：
    - workspace_root：工作区根目录
    - overlay：SDK overlay 路径
    - approval_provider/human_io：宿主注入（可选；工具调用需要）
    - sdk_backend：可选注入的 SDK ChatBackend（离线用）

    返回：
    - Runtime 实例
    """

    agently_agent = None
    if sdk_backend is None:
        try:
            from agently import Agently  # type: ignore
        except ModuleNotFoundError as exc:
            raise RuntimeError("agently is required for real mode (bridge)") from exc

        base_url = env_or_default("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model_name = env_or_default("MODEL_NAME", "gpt-4o-mini")
        api_key = env_or_default("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("missing OPENAI_API_KEY")

        Agently.set_settings(
            "OpenAICompatible",
            {"base_url": base_url, "model": model_name, "auth": api_key},
        )
        agently_agent = Agently.create_agent()

    return Runtime(
        RuntimeConfig(
            mode="bridge",
            workspace_root=workspace_root,
            sdk_config_paths=[overlay],
            preflight_mode="off",
            agently_agent=agently_agent,
            approval_provider=approval_provider,
            human_io=human_io,
            sdk_backend=sdk_backend,
            output_validation_mode=output_validation_mode,  # type: ignore[arg-type]
            output_validator=output_validator,
        )
    )


def build_evidence_strict_output_validator(
    *,
    schema_id: str,
    require_file_writes: Optional[List[str]] = None,
    require_tools_ok: Optional[List[str]] = None,
    forbid_file_writes: Optional[List[str]] = None,
) -> Callable[..., Dict[str, Any]]:
    """
    构造 evidence-strict 的 output_validator（用于 RuntimeConfig.output_validator）。

    说明：
    - 校验只基于 `NodeReport.tool_calls`（证据链真相源），避免扫描 WAL 原文；
    - 只做最小可披露摘要：errors 列表（kind/path/message）。

    参数：
    - schema_id：输出校验 schema id（写入 meta.output_validation.schema_id）
    - require_file_writes：必须出现的 `file_write` 目标路径列表（相对 workspace）
    - require_tools_ok：必须出现且 ok=True 的工具名列表（如 shell_exec/apply_patch）
    - forbid_file_writes：禁止出现的 `file_write` 目标路径列表（用于约束“不得用 file_write 重写基线文件”）
    """

    required_files = list(require_file_writes or [])
    required_tools = list(require_tools_ok or [])
    forbidden_files = list(forbid_file_writes or [])

    def _validate(*, final_output: str, node_report: Any, context: Dict[str, Any]) -> Dict[str, Any]:
        _ = (final_output, context)
        errors: List[Dict[str, Any]] = []

        tool_calls = getattr(node_report, "tool_calls", None) or []

        def _has_file_write(path: str) -> bool:
            for t in tool_calls:
                if getattr(t, "name", None) != "file_write":
                    continue
                if getattr(t, "ok", False) is not True:
                    continue
                data = getattr(t, "data", None) or {}
                if isinstance(data, dict) and str(data.get("path") or "") == str(path):
                    return True
            return False

        def _has_tool_ok(name: str) -> bool:
            for t in tool_calls:
                if getattr(t, "name", None) != name:
                    continue
                if getattr(t, "ok", False) is True:
                    return True
            return False

        def _has_forbidden_file_write(path: str) -> bool:
            for t in tool_calls:
                if getattr(t, "name", None) != "file_write":
                    continue
                data = getattr(t, "data", None) or {}
                if isinstance(data, dict) and str(data.get("path") or "") == str(path):
                    return True
            return False

        for p in required_files:
            if not _has_file_write(p):
                errors.append({"kind": "missing_tool_evidence", "path": p, "message": "missing file_write evidence"})

        for name in required_tools:
            if not _has_tool_ok(name):
                errors.append({"kind": "missing_tool_evidence", "path": name, "message": "missing tool ok evidence"})

        for p in forbidden_files:
            if _has_forbidden_file_write(p):
                errors.append({"kind": "forbidden_tool_evidence", "path": p, "message": "forbidden file_write evidence"})

        return {"ok": len(errors) == 0, "schema_id": schema_id, "errors": errors}

    return _validate
