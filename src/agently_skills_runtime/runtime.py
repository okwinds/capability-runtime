"""
AgentlySkillsRuntime：桥接层主入口。

职责：
- 构造 SDK Agent（核心引擎），注入 AgentlyChatBackend（LLM 传输适配）
- 提供 preflight gate（生产默认 fail-closed）
- 提供 upstream fork 校验（可选：off/warn/strict）
- 运行并聚合事件为 NodeReport v2，返回 NodeResult

对齐规格：
- `docs/specs/engineering-spec/02_Technical_Design/PUBLIC_API.md`
- `docs/specs/engineering-spec/02_Technical_Design/SKILLS_PREFLIGHT.md`
- `docs/specs/engineering-spec/04_Operations/CONFIGURATION.md`
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import yaml

from agent_sdk.config.defaults import load_default_config_dict
from agent_sdk.config.loader import AgentSdkConfig, load_config_dicts
from agent_sdk.core.agent import Agent
from agent_sdk.core.errors import FrameworkError, FrameworkIssue
from agent_sdk.safety.approvals import ApprovalProvider
from agent_sdk.skills.manager import SkillsManager
from agent_sdk.tools.protocol import HumanIOProvider

from .adapters.agently_backend import AgentlyBackendConfig, AgentlyChatBackend, build_openai_compatible_requester_factory
from .adapters.triggerflow_tool import TriggerFlowRunner, TriggerFlowToolDeps, build_triggerflow_run_flow_tool
from .reporting.node_report import NodeReportBuilder
from .types import NodeReportV2, NodeResultV2


PreflightMode = Literal["error", "warn", "off"]
BackendMode = Literal["agently_openai_compatible", "sdk_openai_chat_completions"]
UpstreamVerificationMode = Literal["off", "warn", "strict"]


@dataclass(frozen=True)
class AgentlySkillsRuntimeConfig:
    """
    桥接层运行配置（最小集合）。

    参数：
    - `workspace_root`：SDK workspace_root（影响 WAL/产物路径与相对路径解析）
    - `config_paths`：SDK overlays（后者覆盖前者）
    - `preflight_mode`：生产接入 gate（error/warn/off）
    - `backend_mode`：LLM backend 选择（默认复用 Agently OpenAICompatible；必要时显式切到 SDK 原生 OpenAI backend）
    - `upstream_verification_mode`：上游 fork 校验模式（off/warn/strict）
    - `agently_fork_root`：期望的 Agently fork 根目录（strict 推荐必填）
    - `skills_runtime_sdk_fork_root`：期望的 skills-runtime-sdk fork 根目录（strict 推荐必填）
    """

    workspace_root: Path
    config_paths: List[Path]
    preflight_mode: PreflightMode = "error"
    backend_mode: BackendMode = "agently_openai_compatible"
    upstream_verification_mode: UpstreamVerificationMode = "warn"
    agently_fork_root: Optional[Path] = None
    skills_runtime_sdk_fork_root: Optional[Path] = None


class AgentlySkillsRuntime:
    """桥接层主入口：在 TriggerFlow 节点内运行 skills runtime。"""

    def __init__(
        self,
        *,
        agently_agent: Any,
        triggerflow_runner: Optional[TriggerFlowRunner] = None,
        config: AgentlySkillsRuntimeConfig,
        env_store: Optional[Dict[str, str]] = None,
        approval_provider: Optional[ApprovalProvider] = None,
        human_io: Optional[HumanIOProvider] = None,
        cancel_checker: Optional[Any] = None,
    ) -> None:
        """
        构造 runtime。

        参数：
        - `agently_agent`：宿主 Agently agent（提供 settings/plugin_manager，用于复用 OpenAICompatible requester）
        - `config`：桥接层配置（workspace_root + overlays + preflight_mode + upstream_verification）
        - `env_store`：session-only env_store（内存 dict；不得落盘 value）
        - `approval_provider`：SDK approvals 注入点（生产建议提供）
        - `human_io`：SDK human IO 注入点（env var 缺失或审批交互时需要）
        - `cancel_checker`：SDK cancel_checker 注入点（Stop/Cancel）
        """

        self._agently_agent = agently_agent
        self._config = config
        self._env_store = dict(env_store or {})
        self._approval_provider = approval_provider
        self._human_io = human_io
        self._cancel_checker = cancel_checker
        self._triggerflow_runner = triggerflow_runner

        if self._config.backend_mode == "agently_openai_compatible":
            requester_factory = build_openai_compatible_requester_factory(agently_agent=agently_agent)
            self._backend = AgentlyChatBackend(config=AgentlyBackendConfig(requester_factory=requester_factory))
        elif self._config.backend_mode == "sdk_openai_chat_completions":
            from agent_sdk.llm.openai_chat import OpenAIChatCompletionsBackend

            cfg = self._load_sdk_config(config_paths=self._config.config_paths)
            api_key_override = None
            try:
                key_name = str(getattr(cfg.llm, "api_key_env") or "")
                if key_name:
                    api_key_override = self._env_store.get(key_name)
            except Exception:
                api_key_override = None
            self._backend = OpenAIChatCompletionsBackend(cfg.llm, api_key=api_key_override)
        else:
            raise ValueError(f"unknown backend_mode: {self._config.backend_mode!r}")

        self._agent: Optional[Agent] = None

    @staticmethod
    def _module_file_path(module_name: str) -> Optional[Path]:
        """
        解析模块文件路径。

        参数：
        - `module_name`：模块名（例如 `agently` / `agent_sdk`）

        返回：
        - 模块 `__file__` 对应的绝对路径；若模块无 `__file__` 返回 `None`。
        """

        mod = importlib.import_module(module_name)
        raw = getattr(mod, "__file__", None)
        if not isinstance(raw, str) or not raw.strip():
            return None
        return Path(raw).expanduser().resolve()

    @staticmethod
    def _is_path_under_root(*, actual_path: Path, expected_root: Path) -> bool:
        """
        判断路径是否位于给定根目录下。

        参数：
        - `actual_path`：实际文件路径
        - `expected_root`：期望根目录

        返回：
        - `True` 表示 `actual_path` 在 `expected_root` 下（含自身）
        """

        try:
            actual_path.resolve().relative_to(expected_root.resolve())
            return True
        except Exception:
            return False

    def verify_upstreams(self) -> List[FrameworkIssue]:
        """
        校验当前导入的上游模块是否来自预期 fork 根目录。

        规则：
        - `off`：不校验，返回空列表。
        - `warn`：若配置了 root 且不匹配，返回 issue（由调用方决定是否仅记录）。
        - `strict`：缺 root / 导入失败 / 路径不匹配均返回 issue（调用方可 fail-closed）。

        返回：
        - `FrameworkIssue` 列表（英文结构化错误）
        """

        mode = self._config.upstream_verification_mode
        if mode == "off":
            return []

        checks = [
            ("agently", self._config.agently_fork_root),
            ("agent_sdk", self._config.skills_runtime_sdk_fork_root),
        ]
        issues: List[FrameworkIssue] = []

        for module_name, expected_root in checks:
            if expected_root is None:
                if mode == "strict":
                    issues.append(
                        FrameworkIssue(
                            code="UPSTREAM_FORK_ROOT_MISSING",
                            message="Expected fork root is required in strict mode.",
                            details={"module": module_name, "mode": mode},
                        )
                    )
                continue

            expected = Path(expected_root).expanduser().resolve()
            try:
                actual = self._module_file_path(module_name)
            except Exception as exc:
                issues.append(
                    FrameworkIssue(
                        code="UPSTREAM_IMPORT_FAILED",
                        message="Upstream module import failed.",
                        details={"module": module_name, "mode": mode, "reason": str(exc)},
                    )
                )
                continue

            if actual is None:
                issues.append(
                    FrameworkIssue(
                        code="UPSTREAM_MODULE_FILE_MISSING",
                        message="Upstream module has no file path.",
                        details={"module": module_name, "mode": mode, "expected_root": str(expected)},
                    )
                )
                continue

            if not self._is_path_under_root(actual_path=actual, expected_root=expected):
                issues.append(
                    FrameworkIssue(
                        code="UPSTREAM_NOT_FROM_EXPECTED_FORK",
                        message="Imported module path is outside expected fork root.",
                        details={
                            "module": module_name,
                            "mode": mode,
                            "expected_root": str(expected),
                            "actual_path": str(actual),
                        },
                    )
                )

        return issues

    def verify_upstreams_or_raise(self) -> None:
        """
        执行上游 fork 校验；若存在问题则抛聚合错误。

        说明：
        - `upstream_verification_mode=off` 时本方法为空操作。
        """

        issues = self.verify_upstreams()
        if not issues:
            return
        raise FrameworkError(
            code="UPSTREAM_VERIFICATION_FAILED",
            message="Upstream fork verification failed.",
            details={"issues": [dataclasses.asdict(i) for i in issues]},
        )

    def _get_or_create_agent(self) -> Agent:
        """
        懒创建 SDK Agent（避免在 preflight gate 失败时就触发 scan/启动期 I/O）。

        返回：
        - `agent_sdk.core.agent.Agent` 实例（缓存复用）
        """

        if self._agent is not None:
            return self._agent

        self._agent = Agent(
            workspace_root=Path(self._config.workspace_root),
            config_paths=list(self._config.config_paths),
            env_vars=self._env_store,
            backend=self._backend,
            human_io=self._human_io,
            approval_provider=self._approval_provider,
            cancel_checker=self._cancel_checker,
        )

        # dev-ready 必备：TriggerFlow tool（宿主注入 runner 时启用）
        if self._triggerflow_runner is not None:
            spec, handler = build_triggerflow_run_flow_tool(deps=TriggerFlowToolDeps(runner=self._triggerflow_runner))
            # SDK Agent 的扩展点：`_extra_tools` 会在每次 run 时被注册到 ToolRegistry。
            # 约束：只在首次构造 Agent 时注入，避免重复注册。
            self._agent._extra_tools.append((spec, handler))  # type: ignore[attr-defined]

        return self._agent

    @staticmethod
    def _load_sdk_config(*, config_paths: List[Path]) -> AgentSdkConfig:
        """
        加载 SDK 配置（default + overlays），用于 preflight（零 I/O）阶段的静态校验。

        参数：
        - `config_paths`：YAML overlays 路径列表（后者覆盖前者）
        """

        default_overlay = load_default_config_dict()
        overlays: List[Dict[str, Any]] = [default_overlay]
        for p in config_paths:
            obj = yaml.safe_load(Path(p).read_text(encoding="utf-8")) or {}
            if isinstance(obj, dict):
                overlays.append(obj)
        return load_config_dicts(overlays)

    def preflight(self) -> List[FrameworkIssue]:
        """
        显式执行 Skills preflight（零 I/O）。

        返回：
        - issues：英文结构化问题列表（errors + warnings）
        """

        cfg = self._load_sdk_config(config_paths=self._config.config_paths)
        mgr = SkillsManager(workspace_root=Path(self._config.workspace_root), skills_config=cfg.skills)
        return mgr.preflight()

    def preflight_or_raise(self) -> None:
        """
        preflight gate（生产默认）：发现任何 issue 则抛出聚合错误。

        注意：
        - 当 upstream 校验模式为 strict 时，会先执行上游校验再执行 skills preflight。
        """

        if self._config.upstream_verification_mode == "strict":
            self.verify_upstreams_or_raise()

        issues = self.preflight()
        if not issues:
            return
        raise FrameworkError(
            code="SKILL_PREFLIGHT_FAILED",
            message="Skills preflight failed.",
            details={"issues": [dataclasses.asdict(i) for i in issues]},
        )

    async def run_async(self, task: str, *, run_id: Optional[str] = None) -> NodeResultV2:
        """
        运行一次任务并返回 NodeResult（异步）。

        参数：
        - `task`：任务文本
        - `run_id`：可选 run_id；不传则由 SDK 生成
        """

        preflight_issues: List[FrameworkIssue] = []
        upstream_issues: List[FrameworkIssue] = []

        # upstream fork 校验 gate（strict fail-closed，warn 仅可观测）
        if self._config.upstream_verification_mode != "off":
            upstream_issues = self.verify_upstreams()
            if upstream_issues and self._config.upstream_verification_mode == "strict":
                report = NodeReportV2(
                    status="failed",
                    reason="upstream_dependency_error",
                    completion_reason="upstream_verification_failed",
                    engine={"name": "skills-runtime-sdk-python", "module": "agent_sdk"},
                    bridge={"name": "agently-skills-runtime"},
                    run_id=run_id or "upstream",
                    events_path=None,
                    activated_skills=[],
                    tool_calls=[],
                    artifacts=[],
                    meta={
                        "upstream_issues": [dataclasses.asdict(i) for i in upstream_issues],
                        "upstream_verification_mode": "strict",
                    },
                )
                return NodeResultV2(final_output="Upstream fork verification failed.", node_report=report, events_path=None, artifacts=[])

        # preflight gate（生产默认 fail-closed；零 I/O）
        if self._config.preflight_mode != "off":
            issues = self.preflight()
            preflight_issues = issues
            if issues and self._config.preflight_mode == "error":
                report = NodeReportV2(
                    status="failed",
                    reason="skill_config_error",
                    completion_reason="preflight_failed",
                    engine={"name": "skills-runtime-sdk-python", "module": "agent_sdk"},
                    bridge={"name": "agently-skills-runtime"},
                    run_id=run_id or "preflight",
                    events_path=None,
                    activated_skills=[],
                    tool_calls=[],
                    artifacts=[],
                    meta={"preflight_issues": [dataclasses.asdict(i) for i in issues]},
                )
                return NodeResultV2(final_output="Skills preflight failed.", node_report=report, events_path=None, artifacts=[])

        events = []
        agent = self._get_or_create_agent()
        async for ev in agent.run_stream_async(task, run_id=run_id):
            events.append(ev)

        report = NodeReportBuilder().build(events=events)
        if preflight_issues and self._config.preflight_mode == "warn":
            report.meta["preflight_issues"] = [dataclasses.asdict(i) for i in preflight_issues]
            report.meta["preflight_mode"] = "warn"
        if upstream_issues and self._config.upstream_verification_mode == "warn":
            report.meta["upstream_issues"] = [dataclasses.asdict(i) for i in upstream_issues]
            report.meta["upstream_verification_mode"] = "warn"

        final_output = ""
        for ev in events:
            if ev.type == "run_completed":
                final_output = str(ev.payload.get("final_output") or "")
            elif ev.type in ("run_failed", "run_cancelled"):
                final_output = str(ev.payload.get("message") or "")

        return NodeResultV2(
            final_output=final_output,
            node_report=report,
            events_path=report.events_path,
            artifacts=[],
        )

    def run(self, task: str, *, run_id: Optional[str] = None) -> NodeResultV2:
        """
        同步运行一次任务（便捷包装）。

        注意：
        - 若当前已在事件循环中（例如 async TriggerFlow chunk），请使用 `run_async`。
        """

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run_async(task, run_id=run_id))
        raise RuntimeError("run() cannot be called from a running event loop; use run_async() instead.")
