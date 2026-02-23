"""
AgentlySkillsRuntime：桥接层主入口。

职责：
- 构造 SDK Agent（核心引擎），注入 AgentlyChatBackend（LLM 传输适配）
- 提供 preflight gate（生产默认 fail-closed）
- 提供 upstream fork 校验（可选：off/warn/strict）
- 运行并聚合事件为 NodeReport v2，返回 NodeResult

对齐规格：
- `docs/internal/specs/engineering-spec/02_Technical_Design/PUBLIC_API.md`
- `docs/internal/specs/engineering-spec/02_Technical_Design/SKILLS_PREFLIGHT.md`
- `docs/internal/specs/engineering-spec/04_Operations/CONFIGURATION.md`
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import importlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Protocol, TypedDict

import yaml

from agent_sdk.config.defaults import load_default_config_dict
from agent_sdk.config.loader import AgentSdkConfig, load_config_dicts
from agent_sdk.core.agent import Agent
from agent_sdk.core.errors import FrameworkError, FrameworkIssue
from agent_sdk.safety.approvals import ApprovalProvider
from agent_sdk.skills.manager import SkillsManager
from agent_sdk.tools.protocol import HumanIOProvider, ToolSpec

from .adapters.agently_backend import AgentlyBackendConfig, AgentlyChatBackend, build_openai_compatible_requester_factory
from .adapters.triggerflow_tool import TriggerFlowRunner, TriggerFlowToolDeps, build_triggerflow_run_flow_tool
from .adapters.upstream import register_agent_tool
from .reporting.node_report import NodeReportBuilder
from .types import NodeReportV2, NodeResultV2


PreflightMode = Literal["error", "warn", "off"]
BackendMode = Literal["agently_openai_compatible", "sdk_openai_chat_completions"]
UpstreamVerificationMode = Literal["off", "warn", "strict"]
SchemaGateMode = Literal["off", "warn", "error"]


class SchemaGateError(TypedDict):
    """SchemaGate 错误条目（脱敏后摘要）。"""

    path: str
    kind: str
    message: str


class SchemaGateResult(TypedDict, total=False):
    """SchemaGate 返回结果（由 Host 提供）。"""

    mode: SchemaGateMode
    ok: bool
    schema_id: Optional[str]
    normalized_payload: Optional[Dict[str, Any]]
    errors: List[SchemaGateError]


class SchemaGate(Protocol):
    """SchemaGate：由宿主注入的可选校验门。"""

    def validate(self, *, final_output: str, node_report: NodeReportV2, context: Dict[str, Any]) -> SchemaGateResult:
        """校验输出并返回结果摘要（不得泄露敏感信息）。"""

        ...


class BridgeHook(Protocol):
    """BridgeHook：由宿主注入的扩展点 hook（bridge core 不实现业务）。"""

    def before_preflight(self, context: Dict[str, Any]) -> None: ...

    def after_preflight(self, context: Dict[str, Any], issues: List[FrameworkIssue]) -> None: ...

    def before_run(self, context: Dict[str, Any]) -> None: ...

    def before_engine_start_turn(self, context: Dict[str, Any]) -> None: ...

    def after_engine_event(self, context: Dict[str, Any], event: Any) -> None: ...

    def before_return_result(self, context: Dict[str, Any], node_result: NodeResultV2) -> None: ...

    def on_error(self, context: Dict[str, Any], error: Exception) -> None: ...


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
        hooks: Optional[List[BridgeHook]] = None,
        schema_gate: Optional[SchemaGate] = None,
        schema_gate_mode: SchemaGateMode = "off",
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
        self._hooks = list(hooks or [])
        self._schema_gate = schema_gate
        self._schema_gate_mode: SchemaGateMode = schema_gate_mode

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
        self._pending_tools: List[Dict[str, Any]] = []

    def register_tool(self, *, spec: ToolSpec, handler: Any, override: bool = False) -> None:
        """
        注册一个自定义 tool 到底层 SDK Agent（公共 API，推荐扩展点）。

        参数：
        - spec：`agent_sdk.tools.protocol.ToolSpec`
        - handler：tool handler（同步函数；签名需兼容 SDK ToolRegistry）
        - override：是否允许覆盖同名 tool（语义与上游对齐）

        说明：
        - 若 SDK Agent 尚未构造：先缓存，待首次 `_get_or_create_agent()` 时统一注入（保持懒加载）；
        - 若 SDK Agent 已构造：立即注入。
        """

        if self._agent is None:
            self._pending_tools.append({"spec": spec, "handler": handler, "override": bool(override)})
            return

        register_agent_tool(agent=self._agent, spec=spec, handler=handler, override=bool(override))

    @staticmethod
    def _sha256_text(text: str) -> str:
        """对文本取 sha256（用于可观测摘要，不落明文）。"""

        return hashlib.sha256((text or "").encode("utf-8")).hexdigest()

    @staticmethod
    def _truncate_text(text: str, *, max_chars: int = 200) -> str:
        """截断文本（用于 meta/error 摘要，避免泄露与膨胀）。"""

        s = str(text or "")
        return s if len(s) <= max_chars else (s[: max_chars - 3] + "...")

    def _record_hook_invocation(
        self,
        *,
        meta: Dict[str, Any],
        name: str,
        ok: bool,
        duration_ms: int,
        error_kind: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """把 hook 调用摘要记录到 NodeReport.meta（不抛异常）。"""

        meta.setdefault("extension_trace", [])
        if isinstance(meta.get("extension_trace"), list):
            meta["extension_trace"].append(
                {"name": name, "ok": ok, "duration_ms": duration_ms, "error_kind": error_kind}
            )
        if not ok and error_message:
            meta.setdefault("extension_errors", [])
            if isinstance(meta.get("extension_errors"), list):
                meta["extension_errors"].append(
                    {
                        "name": name,
                        "error_kind": error_kind or "exception",
                        "message": self._truncate_text(error_message),
                    }
                )

    def _safe_call_hook(self, *, meta: Dict[str, Any], name: str, fn) -> None:  # type: ignore[no-untyped-def]
        """安全调用 hook：记录耗时与异常，不影响主流程。"""

        started = time.monotonic()
        try:
            fn()
            dur_ms = int((time.monotonic() - started) * 1000)
            self._record_hook_invocation(meta=meta, name=name, ok=True, duration_ms=dur_ms)
        except Exception as exc:
            dur_ms = int((time.monotonic() - started) * 1000)
            self._record_hook_invocation(
                meta=meta,
                name=name,
                ok=False,
                duration_ms=dur_ms,
                error_kind=type(exc).__name__,
                error_message=str(exc),
            )

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
            # 上游公开扩展点优先；旧版兼容回退到 `_extra_tools`（见 adapters/upstream.py）。
            # 约束：只在首次构造 Agent 时注入，避免重复注册。
            register_agent_tool(agent=self._agent, spec=spec, handler=handler, override=False)

        # 宿主注入的自定义 tools（通过公共 API register_tool 缓存）
        pending = list(self._pending_tools)
        self._pending_tools.clear()
        for item in pending:
            spec = item.get("spec")
            handler = item.get("handler")
            override = bool(item.get("override"))
            if spec is None or handler is None:
                continue
            register_agent_tool(agent=self._agent, spec=spec, handler=handler, override=override)

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

    async def run_async(
        self,
        task: str,
        *,
        run_id: Optional[str] = None,
        initial_history: Optional[List[Dict[str, Any]]] = None,
        session_id: Optional[str] = None,
        turn_id: Optional[str] = None,
    ) -> NodeResultV2:
        """
        运行一次任务并返回 NodeResult（异步）。

        参数：
        - `task`：任务文本
        - `run_id`：可选 run_id；不传则由 SDK 生成
        - `initial_history`：宿主注入的历史消息/上下文（会话恢复 / RAG 注入）
        - `session_id`：宿主侧会话标识（写入 NodeReport.meta）
        - `turn_id`：宿主侧 turn 标识（写入 NodeReport.meta，字段名为 host_turn_id）
        """

        bridge_meta: Dict[str, Any] = {
            "initial_history_injected": initial_history is not None,
            "task_sha256": self._sha256_text(task),
            "task_len": len(task or ""),
        }
        if session_id is not None:
            bridge_meta["session_id"] = session_id
        if turn_id is not None:
            bridge_meta["host_turn_id"] = turn_id

        hook_context: Dict[str, Any] = {
            "run_id": run_id,
            "turn_id": None,
            "session_id": session_id,
            "host_turn_id": turn_id,
            # hook_context 允许宿主侧做观测/审计/调试；默认仅给截断版，避免泄露与膨胀。
            "task": self._truncate_text(task, max_chars=200),
            "task_sha256": bridge_meta.get("task_sha256"),
            "initial_history_injected": bridge_meta.get("initial_history_injected"),
            "config_snapshot": {
                "workspace_root": str(self._config.workspace_root),
                "config_paths": [str(p) for p in self._config.config_paths],
                "preflight_mode": self._config.preflight_mode,
                "backend_mode": self._config.backend_mode,
                "upstream_verification_mode": self._config.upstream_verification_mode,
                "schema_gate_mode": self._schema_gate_mode,
            },
        }

        for h in self._hooks:
            fn = getattr(h, "before_preflight", None)
            if callable(fn):
                self._safe_call_hook(meta=bridge_meta, name="before_preflight", fn=lambda fn=fn: fn(hook_context))

        preflight_issues: List[FrameworkIssue] = []
        upstream_issues: List[FrameworkIssue] = []

        # upstream fork 校验 gate（strict fail-closed，warn 仅可观测）
        if self._config.upstream_verification_mode != "off":
            upstream_issues = self.verify_upstreams()

        # preflight gate（生产默认 fail-closed；零 I/O）
        if self._config.preflight_mode != "off":
            preflight_issues = self.preflight()

        for h in self._hooks:
            fn = getattr(h, "after_preflight", None)
            if callable(fn):
                issues = [*upstream_issues, *preflight_issues]
                self._safe_call_hook(
                    meta=bridge_meta,
                    name="after_preflight",
                    fn=lambda fn=fn, issues=issues: fn(hook_context, issues),
                )

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
                    **bridge_meta,
                },
            )
            node_result = NodeResultV2(final_output="Upstream fork verification failed.", node_report=report, events_path=None, artifacts=[])
            for h in self._hooks:
                fn = getattr(h, "before_return_result", None)
                if callable(fn):
                    self._safe_call_hook(
                        meta=report.meta,
                        name="before_return_result",
                        fn=lambda fn=fn, node_result=node_result: fn(hook_context, node_result),
                    )
            return node_result

        if preflight_issues and self._config.preflight_mode == "error":
            issues_payload = [dataclasses.asdict(i) for i in preflight_issues]
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
                meta={
                    # 对齐契约：preflight 失败时应提供 `meta.skill_issue={code,message,details}`。
                    "skill_issue": {
                        "code": "SKILL_PREFLIGHT_FAILED",
                        "message": "Skills preflight failed.",
                        "details": {"issues": issues_payload},
                    },
                    # 兼容保留：保留旧字段，避免历史用例断链。
                    "preflight_issues": issues_payload,
                    **bridge_meta,
                },
            )
            node_result = NodeResultV2(final_output="Skills preflight failed.", node_report=report, events_path=None, artifacts=[])
            for h in self._hooks:
                fn = getattr(h, "before_return_result", None)
                if callable(fn):
                    self._safe_call_hook(
                        meta=report.meta,
                        name="before_return_result",
                        fn=lambda fn=fn, node_result=node_result: fn(hook_context, node_result),
                    )
            return node_result

        events: List[Any] = []
        agent = self._get_or_create_agent()
        saw_before_run = False
        saw_before_turn = False
        try:
            async for ev in agent.run_stream_async(task, run_id=run_id, initial_history=initial_history):
                events.append(ev)

                if not saw_before_run and ev.type == "run_started":
                    hook_context["run_id"] = ev.run_id
                    for h in self._hooks:
                        fn = getattr(h, "before_run", None)
                        if callable(fn):
                            self._safe_call_hook(meta=bridge_meta, name="before_run", fn=lambda fn=fn: fn(hook_context))
                    saw_before_run = True

                if not saw_before_turn and getattr(ev, "turn_id", None):
                    hook_context["turn_id"] = ev.turn_id
                    for h in self._hooks:
                        fn = getattr(h, "before_engine_start_turn", None)
                        if callable(fn):
                            self._safe_call_hook(meta=bridge_meta, name="before_engine_start_turn", fn=lambda fn=fn: fn(hook_context))
                    saw_before_turn = True

                for h in self._hooks:
                    fn = getattr(h, "after_engine_event", None)
                    if callable(fn):
                        self._safe_call_hook(
                            meta=bridge_meta,
                            name="after_engine_event",
                            fn=lambda fn=fn, ev=ev: fn(hook_context, ev),
                        )
        except Exception as exc:
            for h in self._hooks:
                fn = getattr(h, "on_error", None)
                if callable(fn):
                    self._safe_call_hook(meta=bridge_meta, name="on_error", fn=lambda fn=fn, exc=exc: fn(hook_context, exc))

            report = NodeReportV2(
                status="failed",
                reason="bridge_error",
                completion_reason="bridge_exception",
                engine={"name": "skills-runtime-sdk-python", "module": "agent_sdk"},
                bridge={"name": "agently-skills-runtime"},
                run_id=str(hook_context.get("run_id") or run_id or "bridge"),
                events_path=None,
                activated_skills=[],
                tool_calls=[],
                artifacts=[],
                meta={
                    "error_kind": type(exc).__name__,
                    "message": self._truncate_text(str(exc)),
                    **bridge_meta,
                },
            )
            node_result = NodeResultV2(final_output="Bridge runtime error.", node_report=report, events_path=None, artifacts=[])
            for h in self._hooks:
                fn = getattr(h, "before_return_result", None)
                if callable(fn):
                    self._safe_call_hook(meta=report.meta, name="before_return_result", fn=lambda fn=fn: fn(hook_context, node_result))
            return node_result

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

        for k, v in bridge_meta.items():
            if v is None:
                continue
            report.meta.setdefault(k, v)

        # Schema Gate（可选，默认 off）
        if self._schema_gate is not None and self._schema_gate_mode != "off" and report.status == "success":
            try:
                sg = self._schema_gate.validate(final_output=final_output, node_report=report, context=dict(hook_context))
                errors_raw = sg.get("errors") or []
                errors_out: List[Dict[str, Any]] = []
                if isinstance(errors_raw, list):
                    for e in errors_raw[:20]:
                        if not isinstance(e, dict):
                            continue
                        errors_out.append(
                            {
                                "path": str(e.get("path") or ""),
                                "kind": str(e.get("kind") or ""),
                                "message": self._truncate_text(str(e.get("message") or "")),
                            }
                        )

                ok = bool(sg.get("ok"))
                out_gate: Dict[str, Any] = {
                    "mode": self._schema_gate_mode,
                    "ok": ok,
                    "schema_id": sg.get("schema_id"),
                    "error_count": len(errors_out),
                    "errors": errors_out,
                }
                normalized_payload = sg.get("normalized_payload")
                if isinstance(normalized_payload, dict):
                    # 默认不落明文，只记录摘要，便于审计与跨系统引用（由 Host 自行存储 payload）。
                    raw = json.dumps(normalized_payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    out_gate["normalized_payload_sha256"] = self._sha256_text(raw.decode("utf-8"))
                    out_gate["normalized_payload_bytes"] = len(raw)
                    out_gate["normalized_payload_top_keys"] = list(normalized_payload.keys())[:20]
                report.meta["schema_gate"] = out_gate
                if self._schema_gate_mode == "error" and not ok:
                    report.meta["schema_gate_overrode_status"] = True
                    report.status = "failed"
                    report.reason = "schema_validation_error"
            except Exception as exc:
                report.meta["schema_gate"] = {
                    "mode": self._schema_gate_mode,
                    "ok": False,
                    "schema_id": None,
                    "error_count": 1,
                    "errors": [{"path": "", "kind": type(exc).__name__, "message": self._truncate_text(str(exc))}],
                }
                if self._schema_gate_mode == "error":
                    report.meta["schema_gate_overrode_status"] = True
                    report.status = "failed"
                    report.reason = "schema_validation_error"

        node_result = NodeResultV2(
            final_output=final_output,
            node_report=report,
            events_path=report.events_path,
            artifacts=[],
        )

        for h in self._hooks:
            fn = getattr(h, "before_return_result", None)
            if callable(fn):
                self._safe_call_hook(meta=report.meta, name="before_return_result", fn=lambda fn=fn: fn(hook_context, node_result))

        return node_result

    def run(
        self,
        task: str,
        *,
        run_id: Optional[str] = None,
        initial_history: Optional[List[Dict[str, Any]]] = None,
        session_id: Optional[str] = None,
        turn_id: Optional[str] = None,
    ) -> NodeResultV2:
        """
        同步运行一次任务（便捷包装）。

        注意：
        - 若当前已在事件循环中（例如 async TriggerFlow chunk），请使用 `run_async`。
        """

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.run_async(
                    task,
                    run_id=run_id,
                    initial_history=initial_history,
                    session_id=session_id,
                    turn_id=turn_id,
                )
            )
        raise RuntimeError("run() cannot be called from a running event loop; use run_async() instead.")
