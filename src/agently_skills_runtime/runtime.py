from __future__ import annotations

"""
统一运行时：声明 → 注册 → 校验 → 执行 → 报告。

定位：
- 对外只提供一个执行入口（Runtime），避免“双入口/双路径”导致的语义分叉；
- mock/bridge/sdk_native 通过 `RuntimeConfig.mode` 切换；
- 控制面证据链以 `NodeReportV2` 为主（事件聚合），数据面输出保持生态兼容。
"""

import asyncio
import hashlib
import inspect
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from skills_runtime.core.contracts import AgentEvent
from skills_runtime.core.errors import FrameworkError, FrameworkIssue
from skills_runtime.skills.manager import SkillsManager

from .config import RuntimeConfig, RuntimeMode, normalize_workspace_root
from .guards import ExecutionGuards
from .protocol.agent import AgentSpec
from .protocol.capability import CapabilityKind, CapabilityResult, CapabilityStatus
from .protocol.context import ExecutionContext, RecursionLimitError
from .protocol.workflow import WorkflowSpec
from .registry import AnySpec, CapabilityRegistry, _get_base
from .reporting.node_report import NodeReportBuilder
from .types import NodeReportV2


@dataclass(frozen=True)
class _SdkInitState:
    """bridge/sdk_native 初始化期的共享资源集合（Runtime 持有，run 期只读使用）。"""

    workspace_root: Path
    config_paths: List[Path]
    skills_config: Any
    skills_config_overlay_issues: List[FrameworkIssue]
    backend: Any
    shared_skills_manager: SkillsManager


class Runtime:
    """
    统一运行时（唯一入口）。

    关键语义：
    - 注册与校验由 Registry 驱动；
    - 执行入口只有 `run()` / `run_stream()`；
    - `run()` 基于 `run_stream()` 实现；
    - 并发安全：per-run guards、per-run SDK Agent（由实现保证不共享可变状态）。
    """

    def __init__(self, config: RuntimeConfig) -> None:
        """
        构造 Runtime。

        参数：
        - config：运行时配置（含 mode 与桥接注入点）
        """

        self._config = config
        self._registry = CapabilityRegistry()
        self._last_node_report: Optional[NodeReportV2] = None
        self._sdk_state: Optional[_SdkInitState] = None
        self._last_lock = asyncio.Lock()
        from .adapters.agent_adapter import AgentAdapter

        self._agent_adapter = AgentAdapter(runtime=self)

        if config.mode in ("bridge", "sdk_native"):
            self._sdk_state = self._init_sdk_state(mode=config.mode)

    @property
    def config(self) -> RuntimeConfig:
        """运行时配置（只读）。"""

        return self._config

    def register(self, spec: AnySpec) -> None:
        """
        注册一个能力。

        参数：
        - spec：AgentSpec 或 WorkflowSpec
        """

        self._registry.register(spec)

    def register_many(self, specs: List[AnySpec]) -> None:
        """批量注册能力。"""

        for s in specs:
            self._registry.register(s)

    @property
    def registry(self) -> CapabilityRegistry:
        """
        能力注册表（只读视角）。

        说明：
        - 主要用于 WorkflowAdapter 递归分发执行时查询 target spec；
        - 调用方不应直接修改内部状态（注册应通过 Runtime.register* 完成）。
        """

        return self._registry

    def validate(self) -> List[str]:
        """
        校验所有依赖，返回缺失能力 ID 列表。

        返回：
        - 缺失 ID 列表；空列表表示全部满足
        """

        return self._registry.validate_dependencies()

    async def run(
        self,
        capability_id: str,
        *,
        input: Optional[Dict[str, Any]] = None,
        context: Optional[ExecutionContext] = None,
    ) -> CapabilityResult:
        """
        非流式执行（等待完成后返回）。

        参数：
        - capability_id：能力 ID
        - input：输入参数 dict
        - context：可选执行上下文（宿主控制；若不传则由 Runtime 创建）
        """

        result: Optional[CapabilityResult] = None
        async for item in self.run_stream(capability_id, input=input, context=context):
            if isinstance(item, CapabilityResult):
                result = item
        if result is None:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error="Runtime.run_stream produced no terminal CapabilityResult",
            )
        return result

    async def run_stream(
        self,
        capability_id: str,
        *,
        input: Optional[Dict[str, Any]] = None,
        context: Optional[ExecutionContext] = None,
    ) -> AsyncIterator[Union[AgentEvent, CapabilityResult]]:
        """
        流式执行：先转发事件（如有），最后产出 CapabilityResult。

        约束：
        - mock 模式可仅产出 CapabilityResult（无中间事件）；
        - bridge/sdk_native 模式 MUST 转发上游 SDK AgentEvent。
        """

        spec = self._registry.get(capability_id)
        if spec is None:
            yield CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"Capability not found: {capability_id!r}",
            )
            return

        guards = ExecutionGuards(max_total_loop_iterations=self._config.max_total_loop_iterations)
        ctx = context or ExecutionContext(
            run_id=uuid.uuid4().hex,
            max_depth=self._config.max_depth,
            guards=guards,
            bag={},
        )
        if ctx.guards is None:
            ctx.guards = guards

        started = time.monotonic()
        if _get_base(spec).kind == CapabilityKind.AGENT:
            async for x in self._execute_agent_stream(spec=spec, input=input or {}, context=ctx):
                if isinstance(x, CapabilityResult):
                    x.duration_ms = (time.monotonic() - started) * 1000
                yield x
            return

        result = await self._execute(spec=spec, input=input or {}, context=ctx)
        result.duration_ms = (time.monotonic() - started) * 1000
        yield result
        return

    async def _execute(self, *, spec: AnySpec, input: Dict[str, Any], context: ExecutionContext) -> CapabilityResult:
        """
        内部执行：创建子 context 并分发到 Agent/Workflow 执行器。

        参数：
        - spec：能力声明
        - input：输入参数
        - context：执行上下文
        """

        base = _get_base(spec)
        try:
            child_ctx = context.child(base.id)
        except RecursionLimitError as exc:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=str(exc),
                metadata={"error_type": "recursion_limit"},
            )

        if base.kind == CapabilityKind.AGENT:
            # 非流式入口内部执行时，仍走流式实现并收敛为最终结果。
            last: Optional[CapabilityResult] = None
            async for item in self._execute_agent_stream(spec=spec, input=input, context=child_ctx):
                if isinstance(item, CapabilityResult):
                    last = item
            return last or CapabilityResult(status=CapabilityStatus.FAILED, error="Agent execution produced no result")

        if not isinstance(spec, WorkflowSpec):
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"Invalid workflow spec type: {type(spec).__name__}",
            )
        from .adapters.workflow_adapter import WorkflowAdapter

        return await WorkflowAdapter().execute(spec=spec, input=input, context=child_ctx, runtime=self)

    async def _execute_agent_stream(
        self, *, spec: AnySpec, input: Dict[str, Any], context: ExecutionContext
    ) -> AsyncIterator[Union[AgentEvent, CapabilityResult]]:
        """
        执行 AgentSpec（流式）。

        说明：
        - mock 模式：直接调用 mock_handler，产出 CapabilityResult；
        - bridge/sdk_native：使用上游 SDK Agent 执行并转发 AgentEvent，最终聚合 NodeReportV2。
        """

        if not isinstance(spec, AgentSpec):
            yield CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"Invalid agent spec type: {type(spec).__name__}",
            )
            return

        async for item in self._agent_adapter.execute_stream(spec=spec, input=input, context=context):
            if isinstance(item, CapabilityResult) and item.node_report is not None:
                async with self._last_lock:
                    self._last_node_report = item.node_report
            yield item

    def _map_node_status(self, report: NodeReportV2) -> CapabilityStatus:
        """
        将 NodeReport 控制面状态映射为 CapabilityStatus。

        约束：
        - needs_approval / incomplete 不得折叠为 failed（避免编排误判）。
        """

        if report.status == "success":
            return CapabilityStatus.SUCCESS
        if report.status == "failed":
            return CapabilityStatus.FAILED
        if report.status == "needs_approval":
            return CapabilityStatus.PENDING
        if report.status == "incomplete":
            return CapabilityStatus.CANCELLED if report.reason == "cancelled" else CapabilityStatus.PENDING
        return CapabilityStatus.FAILED

    def _build_fail_closed_report(
        self,
        *,
        run_id: str,
        status: str,
        reason: Optional[str],
        completion_reason: str,
        meta: Dict[str, Any],
    ) -> NodeReportV2:
        """
        构造不依赖事件流的最小 NodeReport（用于 fail-closed 分支）。

        说明：
        - preflight/output validator 等 gate 可能在启动引擎前返回；
        - 仍需产出稳定的 engine/bridge 身份信息，供编排与审计使用；
        - events_path 在此分支为 None（不得伪造）。
        """

        import importlib.metadata

        def _get_version(names: List[str]) -> Optional[str]:
            # 证据链上优先使用 skills_runtime.__version__（比 dist-info 更可靠，尤其在 editable 安装场景）。
            if any(n in ("skills-runtime-sdk", "skills-runtime-sdk-python") for n in names):
                try:
                    import skills_runtime  # type: ignore

                    v = getattr(skills_runtime, "__version__", None)
                    if isinstance(v, str) and v.strip():
                        return v.strip()
                except Exception:
                    pass
            for n in names:
                try:
                    return importlib.metadata.version(n)
                except Exception:
                    continue
            return None

        return NodeReportV2(
            status=status,  # type: ignore[arg-type]
            reason=reason,
            completion_reason=completion_reason,
            engine={
                "name": "skills-runtime-sdk-python",
                "module": "skills_runtime",
                "version": _get_version(["skills-runtime-sdk", "skills-runtime-sdk-python"]),
            },
            bridge={
                "name": "agently-skills-runtime",
                "version": _get_version(["agently-skills-runtime"]),
            },
            run_id=run_id,
            turn_id=None,
            events_path=None,
            activated_skills=[],
            tool_calls=[],
            artifacts=[],
            meta=dict(meta or {}),
        )

    def _apply_output_validation(
        self,
        *,
        final_output: str,
        report: NodeReportV2,
        context: Dict[str, Any],
    ) -> None:
        """
        调用 output_validator 并把“最小披露”的摘要写入 NodeReport.meta。

        行为：
        - mode=off：不调用
        - mode=warn：记录摘要但不覆盖状态
        - mode=error：validator 返回 ok=False 时覆盖为 failed（可回归护栏）
        """

        mode = self._config.output_validation_mode
        validator = self._config.output_validator
        if mode == "off" or validator is None:
            return

        try:
            # 推荐签名：validate(*, final_output=..., node_report=..., context=...)
            raw = validator(final_output=final_output, node_report=report, context=context)
        except TypeError:
            raw = validator(final_output, report, context)
        except Exception as exc:
            # validator 自身异常：作为可观测信息记录；不强行失败（避免“验证器把系统打挂”）。
            report.meta["output_validation"] = {
                "mode": mode,
                "ok": False,
                "error": f"validator_exception:{type(exc).__name__}",
            }
            if mode == "error":
                report.status = "failed"
                report.reason = "output_validation_error"
                report.meta["output_validation_overrode_status"] = True
            return

        if not isinstance(raw, dict):
            report.meta["output_validation"] = {"mode": mode, "ok": True, "note": "validator_return_not_dict"}
            return

        ok = bool(raw.get("ok", True))
        schema_id = raw.get("schema_id") if isinstance(raw.get("schema_id"), str) else None
        errors = raw.get("errors") if isinstance(raw.get("errors"), list) else []

        summary: Dict[str, Any] = {"mode": mode, "ok": ok}
        if schema_id:
            summary["schema_id"] = schema_id
        if errors:
            # errors 期望是可披露的摘要条目（path/kind/message）
            summary["errors"] = errors

        normalized_payload = raw.get("normalized_payload")
        if isinstance(normalized_payload, dict):
            payload_text = json.dumps(normalized_payload, ensure_ascii=False, separators=(",", ":"))
            digest = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            summary["normalized_payload_sha256"] = digest
            summary["normalized_payload_bytes"] = len(payload_text.encode("utf-8"))
            summary["normalized_payload_top_keys"] = sorted(list(normalized_payload.keys()))[:20]

        report.meta["output_validation"] = summary

        if (not ok) and mode == "error":
            report.status = "failed"
            report.reason = "output_validation_error"
            report.meta["output_validation_overrode_status"] = True

    def _redact_issue(self, issue: FrameworkIssue) -> Dict[str, Any]:
        """Runtime 内部包装：复用模块级 `_redact_issue`。"""

        return _redact_issue(issue)

    def _get_host_meta(self, *, context: ExecutionContext) -> Dict[str, Any]:
        """Runtime 内部包装：复用模块级 `_get_host_meta`。"""

        return _get_host_meta(context=context)

    def _call_callback(self, cb, *args: Any) -> None:
        """Runtime 内部包装：复用模块级 `_call_callback`。"""

        _call_callback(cb, *args)

    def _build_task(self, *, spec: AgentSpec, input: Dict[str, Any]) -> str:
        """
        将 AgentSpec + input 转换为 SDK Agent 的 task 文本（结构化拼接）。

        约束：
        - 不做 prompt engineering；
        - 仅做结构化拼接，保证可回归与可诊断。
        """

        parts: List[str] = []
        if spec.base.description:
            parts.append(f"## 任务\n{spec.base.description}")

        if input:
            lines: List[str] = []
            for k, v in input.items():
                if isinstance(v, str):
                    lines.append(f"- {k}: {v}")
                else:
                    lines.append(f"- {k}: {json.dumps(v, ensure_ascii=False)}")
            parts.append("## 输入\n" + "\n".join(lines))

        if spec.output_schema and spec.output_schema.fields:
            schema_lines = [f"- {name}: {typ}" for name, typ in spec.output_schema.fields.items()]
            parts.append("## 输出要求\n请严格按以下字段输出 JSON：\n" + "\n".join(schema_lines))

        if spec.prompt_template:
            parts.append(str(spec.prompt_template))

        return "\n\n".join(parts)

    def _init_sdk_state(self, *, mode: RuntimeMode) -> _SdkInitState:
        """
        初始化 bridge/sdk_native 的共享资源（backend + SkillsManager）。

        参数：
        - mode：bridge 或 sdk_native
        """

        workspace_root = normalize_workspace_root(self._config.workspace_root)
        config_paths = [Path(p).expanduser().resolve() for p in self._config.sdk_config_paths]

        from skills_runtime.config.defaults import load_default_config_dict
        from skills_runtime.config.loader import load_config_dicts

        overlays: List[Dict[str, Any]] = [load_default_config_dict()]
        overlay_issues: List[FrameworkIssue] = []
        for p in config_paths:
            try:
                raw = _load_yaml_dict(p)
                sanitized, issues = _sanitize_sdk_overlay_dict_for_loader(raw)
                overlays.append(sanitized)
                overlay_issues.extend(issues)
            except Exception:
                overlays.append({})
        cfg = load_config_dicts(overlays)

        if self._config.skills_config is not None:
            skills_cfg = _normalize_skills_config_for_skills_runtime(self._config.skills_config)
        else:
            skills_cfg = cfg.skills

        backend: Any
        if self._config.sdk_backend is not None:
            # 离线/测试注入：允许用 FakeChatBackend 等驱动真实 Agent loop，产出完整证据链。
            backend = self._config.sdk_backend
        elif mode == "bridge":
            if self._config.agently_agent is None:
                raise ValueError("RuntimeConfig.agently_agent is required when mode='bridge'")
            from .adapters.agently_backend import (
                AgentlyBackendConfig,
                AgentlyChatBackend,
                build_openai_compatible_requester_factory,
            )

            requester_factory = build_openai_compatible_requester_factory(agently_agent=self._config.agently_agent)
            backend = AgentlyChatBackend(config=AgentlyBackendConfig(requester_factory=requester_factory))
        else:
            from skills_runtime.llm.openai_chat import OpenAIChatCompletionsBackend

            backend = OpenAIChatCompletionsBackend(cfg.llm)

        shared_skills_manager = SkillsManager(
            workspace_root=workspace_root,
            skills_config=skills_cfg,
            in_memory_registry=self._config.in_memory_skills or {},
        )

        try:
            report = shared_skills_manager.scan()
        except Exception:
            report = None

        if report is not None and getattr(report, "errors", None) and self._config.preflight_mode == "error":
            raise FrameworkError(
                code="SKILL_SCAN_FAILED",
                message="Skills scan failed during Runtime initialization.",
                details={"errors": getattr(report, "errors", [])},
            )

        return _SdkInitState(
            workspace_root=workspace_root,
            config_paths=config_paths,
            skills_config=skills_cfg,
            skills_config_overlay_issues=list(overlay_issues),
            backend=backend,
            shared_skills_manager=shared_skills_manager,
        )

    def _preflight(self) -> List[FrameworkIssue]:
        """
        执行 skills preflight（零 I/O）。

        返回：
        - FrameworkIssue 列表；空列表表示通过
        """

        if self._sdk_state is None:
            return []
        try:
            mgr = SkillsManager(
                workspace_root=self._sdk_state.workspace_root,
                skills_config=_normalize_skills_config_for_skills_runtime(self._sdk_state.skills_config),
            )
            upstream_issues = mgr.preflight()
            overlay_issues = list(getattr(self._sdk_state, "skills_config_overlay_issues", []) or [])
            return overlay_issues + list(upstream_issues or [])
        except Exception as exc:
            # preflight 异常不得 fail-open：否则 `preflight_mode="error"` 的 gate 会被静默绕过。
            return [
                FrameworkIssue(
                    code="SKILL_PREFLIGHT_EXCEPTION",
                    message="Skills preflight raised exception",
                    details={"exception_type": type(exc).__name__},
                )
            ]

    def _create_sdk_agent(self) -> Any:
        """
        创建 per-run SDK Agent 实例（避免跨 run 共享可变状态）。

        返回：
        - skills_runtime.core.agent.Agent 实例
        """

        if self._sdk_state is None:
            raise RuntimeError("SDK state is not initialized")

        from skills_runtime.core.agent import Agent

        kwargs: Dict[str, Any] = {
            "workspace_root": self._sdk_state.workspace_root,
            "config_paths": list(self._sdk_state.config_paths),
            "env_vars": dict(self._config.env_vars),
            "backend": self._sdk_state.backend,
            "human_io": self._config.human_io,
            "approval_provider": self._config.approval_provider,
            "cancel_checker": self._config.cancel_checker,
            "exec_sessions": self._config.exec_sessions,
            "collab_manager": self._config.collab_manager,
            "skills_manager": self._sdk_state.shared_skills_manager,
            # 建设期：直接依赖新版上游 WAL 抽象（不做旧版兼容探测）。
            "wal_backend": self._config.wal_backend,
        }

        agent = Agent(**kwargs)

        for t in self._config.custom_tools:
            agent.register_tool(t.spec, t.handler, override=bool(t.override))

        return agent

    @property
    def last_node_report(self) -> Optional[NodeReportV2]:
        """最近一次 bridge/sdk_native 执行产出的 NodeReport（可选便利属性）。"""

        return self._last_node_report


def _load_yaml_dict(path: Path) -> Dict[str, Any]:
    """
    读取 YAML 文件并返回 dict。

    说明：
    - 该函数仅用于加载 SDK overlays；
    - 解析失败时抛异常，由调用方决定容错策略。
    """

    import yaml

    obj = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(obj, dict):
        raise ValueError("YAML root must be a mapping")
    return obj


def _normalize_skills_config_for_skills_runtime(skills_config: Any) -> Any:
    """
    将 RuntimeConfig.skills_config 归一为上游 skills config 可接受的形态（dict 或 model）。

    背景：
    - `skills-runtime-sdk>=1.0` 对 skills 配置 schema 采用 `extra=forbid`，未知字段会直接导致校验异常；
    - 本仓历史上允许在 `skills_config` dict 里包含一些旧字段（例如 `roots/mode/max_auto`），需要在桥接层做最小兼容，
      以便“warn 模式可继续跑、error 模式可 fail-closed”由 preflight gate 决定，而不是初始化期直接崩溃。

    参数：
    - skills_config：可能为 dict / pydantic model / 其它对象

    返回：
    - 归一后的 skills_config（尽量保持调用方意图；无法识别时原样返回）
    """

    if not isinstance(skills_config, dict):
        return skills_config

    # 兼容：允许传入完整 SDK config（包含 skills 根节点）
    if isinstance(skills_config.get("skills"), dict):
        skills_config = dict(skills_config["skills"])

    allowed_keys = {
        "env_var_missing_policy",
        "versioning",
        "strictness",
        "spaces",
        "sources",
        "scan",
        "injection",
        "actions",
        "references",
    }
    # 兼容：历史字段（上游 1.x 不再支持），由本仓 preflight/文档提示用户迁移
    legacy_keys = {"roots", "mode", "max_auto"}

    out: Dict[str, Any] = {}
    for k, v in dict(skills_config).items():
        if k in allowed_keys:
            out[k] = v
        elif k in legacy_keys:
            continue
        else:
            # 未知字段：不在这里直接抛错（由 preflight gate 控制 fail-closed），
            # 但必须过滤掉以避免 SDK loader/model_validate 直接异常。
            continue

    # === v0.1.5 兼容：skills.spaces schema（account/domain ↔ namespace）===
    #
    # 说明：
    # - 上游 v0.1.5 将 spaces 从 account/domain 升级为 namespace，并在 loader 层显式拒绝 legacy 字段；
    # - 本仓需要在进入上游 loader 前做最小转换，避免初始化期直接崩溃；
    # - 若 namespace 无法无损映射回 legacy（多段），必须 fail-closed，避免产生错误定位。
    spaces = out.get("spaces")
    if spaces is not None:
        from .upstream_compat import detect_skills_space_schema, normalize_spaces_for_upstream

        target_schema = detect_skills_space_schema()
        normalized, warnings = normalize_spaces_for_upstream(spaces=spaces, target_schema=target_schema)
        if normalized is not None:
            out["spaces"] = normalized
        elif warnings:
            raise FrameworkError(
                code="SKILL_CONFIG_SPACES_SCHEMA_INCOMPATIBLE",
                message="skills.spaces schema is incompatible with installed skills-runtime-sdk",
                details={"target_schema": target_schema, "warnings": warnings},
            )
    return out


def _sanitize_sdk_overlay_dict_for_loader(overlay: Dict[str, Any]) -> tuple[Dict[str, Any], List[FrameworkIssue]]:
    """
    在调用上游 `load_config_dicts()` 前，对 overlay 做“最小清洗”，避免未知字段导致初始化期直接崩溃。

    说明：
    - 上游 `AgentSdkConfig/AgentSdkSkillsConfig` 默认 `extra=forbid`，因此 overlay 内出现未知字段会直接抛校验异常；
    - 本仓需要在 preflight gate 中把问题以 `FrameworkIssue` 可观测化，并允许 warn 模式继续执行。

    当前清洗范围（最小集合，覆盖本仓离线回归用例）：
    - `skills.roots`：历史字段，产生 `SKILL_CONFIG_LEGACY_ROOTS_UNSUPPORTED` 并移除；
    - `skills.scan` 下未知字段：产生 `SKILL_CONFIG_UNKNOWN_SCAN_OPTION` 并移除未知 key。

    参数：
    - overlay：单个 YAML overlay 的 dict（可包含多个顶层段）

    返回：
    - sanitized_overlay：移除已知不兼容字段后的 overlay
    - issues：对应的 FrameworkIssue 列表（供 preflight gate 决策）
    """

    if not isinstance(overlay, dict):
        return {}, []

    issues: List[FrameworkIssue] = []
    sanitized: Dict[str, Any] = dict(overlay)

    skills = sanitized.get("skills")
    if not isinstance(skills, dict):
        return sanitized, issues

    skills_obj: Dict[str, Any] = dict(skills)

    if "roots" in skills_obj:
        issues.append(
            FrameworkIssue(
                code="SKILL_CONFIG_LEGACY_ROOTS_UNSUPPORTED",
                message="skills.roots is a legacy option and is not supported by skills-runtime-sdk>=1.x",
                details={"path": "skills.roots"},
            )
        )
        skills_obj.pop("roots", None)

    # v0.1.5 兼容：spaces schema（account/domain ↔ namespace）
    spaces = skills_obj.get("spaces")
    if spaces is not None:
        from .upstream_compat import detect_skills_space_schema, normalize_spaces_for_upstream

        target_schema = detect_skills_space_schema()
        normalized, warnings = normalize_spaces_for_upstream(spaces=spaces, target_schema=target_schema)
        if normalized is not None:
            skills_obj["spaces"] = normalized
            for w in warnings:
                issues.append(
                    FrameworkIssue(
                        code="SKILL_CONFIG_SPACES_SCHEMA_NORMALIZED",
                        message="skills.spaces schema normalized for upstream compatibility",
                        details={"path": "skills.spaces", "target_schema": target_schema, "warning": w},
                    )
                )
        elif warnings:
            # overlay 的目标是“不让初始化期直接崩”，因此这里做 best-effort：丢弃 spaces 并把原因写入 issues。
            skills_obj.pop("spaces", None)
            issues.append(
                FrameworkIssue(
                    code="SKILL_CONFIG_SPACES_SCHEMA_INCOMPATIBLE_DROPPED",
                    message="skills.spaces is incompatible with installed skills-runtime-sdk; dropped from overlay",
                    details={"path": "skills.spaces", "target_schema": target_schema, "warnings": warnings},
                )
            )

    scan = skills_obj.get("scan")
    if isinstance(scan, dict):
        scan_obj: Dict[str, Any] = dict(scan)
        allowed_scan_keys = {
            "ignore_dot_entries",
            "max_depth",
            "max_dirs_per_root",
            "max_frontmatter_bytes",
            "refresh_policy",
            "ttl_sec",
        }
        unknown = [k for k in scan_obj.keys() if k not in allowed_scan_keys]
        for k in unknown:
            issues.append(
                FrameworkIssue(
                    code="SKILL_CONFIG_UNKNOWN_SCAN_OPTION",
                    message="Unknown skills.scan option is not supported.",
                    details={"path": f"skills.scan.{k}", "key": k},
                )
            )
            scan_obj.pop(k, None)
        skills_obj["scan"] = scan_obj

    sanitized["skills"] = skills_obj
    return sanitized, issues


def _redact_issue(issue: FrameworkIssue) -> Dict[str, Any]:
    """
    把 FrameworkIssue 归一为“可诊断但最小披露”的 dict。

    说明：
    - 避免把 details 原样透传导致泄露或膨胀；
    - 当前仅保留 code/message，并在 details 里保留常见定位字段（若存在）。
    """

    code = str(getattr(issue, "code", "") or "")
    message = str(getattr(issue, "message", "") or "")
    details = getattr(issue, "details", None)
    out: Dict[str, Any] = {"code": code, "message": message}
    if isinstance(details, dict):
        slim: Dict[str, Any] = {}
        for k in ("path", "source", "kind"):
            v = details.get(k)
            if isinstance(v, str) and v:
                slim[k] = v
        if slim:
            out["details"] = slim
    return out


def _get_host_meta(*, context: ExecutionContext) -> Dict[str, Any]:
    """
    从 ExecutionContext.bag 中读取 host-meta（保留字段）。

    约定：
    - 该字段为框架保留键，不应与业务输入冲突；
    - 结构：{"session_id": str, "host_turn_id": str, "initial_history": list[dict]}
    """

    raw = context.bag.get("__host_meta__")
    return raw if isinstance(raw, dict) else {}


def _call_callback(cb, *args: Any) -> None:
    """
    以“尽量兼容”的方式调用 callback。

    说明：
    - 支持 cb(a) 或 cb(a, b) 两种签名；
    - 若签名/调用失败，抛异常由调用方决定是否吞掉。
    """

    try:
        sig = inspect.signature(cb)
    except Exception:
        sig = None

    if sig is not None and len(sig.parameters) >= len(args):
        cb(*args)
        return

    # 回退：尽量调用最短参数版本
    if args:
        cb(args[0])
        return
    cb()
