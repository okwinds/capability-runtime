from __future__ import annotations

"""SDK 生命周期组件：初始化、预检与 per-run Agent 创建。"""

from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator, AsyncIterator, Dict, List, Optional

from skills_runtime.core.contracts import AgentEvent
from skills_runtime.core.errors import FrameworkError, FrameworkIssue
from skills_runtime.llm.chat_sse import ChatStreamEvent
from skills_runtime.llm.protocol import ChatRequest
from skills_runtime.skills.manager import SkillsManager

from .config import CustomTool, RuntimeConfig, RuntimeMode, normalize_workspace_root
from .logging_utils import log_suppressed_exception
from .protocol.chat_backend import ChatBackendProtocol


@dataclass(frozen=True)
class _SdkInitState:
    """bridge/sdk_native 初始化期共享资源集合（run 期只读）。"""

    workspace_root: Path
    config_paths: List[Path]
    skills_config: Any
    skills_config_overlay_issues: List[FrameworkIssue]
    skills_scan_issues: List[FrameworkIssue]
    backend: Any
    shared_skills_manager: SkillsManager


class SdkLifecycle:
    """封装 SDK 初始化、preflight 与 Agent 实例创建。"""

    def __init__(self, config: RuntimeConfig) -> None:
        """
        初始化 SDK 生命周期状态。

        参数：
        - config：Runtime 配置
        """

        mode = str(getattr(config, "mode", ""))
        if mode not in ("bridge", "sdk_native"):
            raise ValueError(f"SdkLifecycle only supports bridge/sdk_native, got: {mode!r}")

        self._config = config
        self._state = self._init_state(mode=mode)  # type: ignore[arg-type]

    @property
    def state(self) -> _SdkInitState:
        """返回初始化后的只读状态。"""

        return self._state

    def preflight(self) -> List[FrameworkIssue]:
        """
        执行 skills preflight（零 I/O）。

        返回：
        - FrameworkIssue 列表；空列表表示通过
        """

        try:
            mgr = SkillsManager(
                workspace_root=self._state.workspace_root,
                skills_config=_normalize_skills_config_for_skills_runtime(self._state.skills_config),
            )
            upstream_issues = mgr.preflight()
            overlay_issues = list(getattr(self._state, "skills_config_overlay_issues", []) or [])
            scan_issues = list(getattr(self._state, "skills_scan_issues", []) or [])
            return overlay_issues + scan_issues + list(upstream_issues or [])
        except Exception as exc:
            # preflight 异常不得 fail-open：否则 preflight_mode="error" gate 会被绕过。
            return [
                FrameworkIssue(
                    code="SKILL_PREFLIGHT_EXCEPTION",
                    message="Skills preflight raised exception",
                    details={"exception_type": type(exc).__name__},
                )
            ]

    def create_agent(self, *, custom_tools: List[CustomTool], llm_config: Optional[Dict[str, Any]] = None) -> Any:
        """
        创建 per-run SDK Agent 实例（避免跨 run 共享可变状态）。

        参数：
        - custom_tools：每次创建 Agent 时要注册的自定义工具列表
        - llm_config：可选 LLM 覆写配置（当前支持 `model`、`tool_choice` 与 `response_format` 字段覆写）
        """

        from skills_runtime.core.agent import Agent

        backend: Any = self._state.backend
        override_model = _extract_model_override(llm_config)
        if override_model is not None:
            backend = _ModelOverrideBackend(backend=backend, model=override_model)

        override_tool_choice = _extract_tool_choice_override(llm_config)
        if override_tool_choice is not None:
            backend = _ToolChoiceOverrideBackend(backend=backend, tool_choice=override_tool_choice)

        override_response_format = _extract_response_format_override(llm_config)
        if override_response_format is not None:
            backend = _ResponseFormatOverrideBackend(backend=backend, response_format=override_response_format)
        usage_bridge_backend = _UsageTapBackend(backend=backend)
        backend = usage_bridge_backend

        kwargs: Dict[str, Any] = {
            "workspace_root": self._state.workspace_root,
            "config_paths": list(self._state.config_paths),
            "env_vars": dict(self._config.env_vars),
            "backend": backend,
            "human_io": self._config.human_io,
            "approval_provider": self._config.approval_provider,
            "cancel_checker": self._config.cancel_checker,
            "exec_sessions": self._config.exec_sessions,
            "collab_manager": self._config.collab_manager,
            "skills_manager": self._state.shared_skills_manager,
            # 建设期：直接依赖新版上游 WAL 抽象（不做旧版兼容探测）。
            "wal_backend": self._config.wal_backend,
        }

        agent = Agent(**kwargs)
        for t in custom_tools:
            agent.register_tool(t.spec, t.handler, override=bool(t.override))
        return _AgentUsageEventBridge(agent=agent, usage_bridge_backend=usage_bridge_backend)

    def _load_sdk_config(self, config_paths: List[Path]) -> tuple[Any, List[FrameworkIssue]]:
        """
        加载 SDK 配置文件并合并 overlays。

        参数：
        - config_paths：配置文件路径列表

        返回：
        - (merged_config, overlay_issues)
        """
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
            except Exception as exc:
                log_suppressed_exception(
                    context="load_sdk_config_overlay",
                    exc=exc,
                    extra={"config_path": str(p)},
                )
                overlay_issues.append(
                    FrameworkIssue(
                        code="SKILL_CONFIG_OVERLAY_LOAD_FAILED",
                        message="Failed to load SDK config overlay; overlay ignored.",
                        details={"path": str(p), "exception_type": type(exc).__name__},
                    )
                )
                if self._config.preflight_mode == "error":
                    raise FrameworkError(
                        code="SKILL_CONFIG_OVERLAY_LOAD_FAILED",
                        message="Failed to load SDK config overlay during Runtime initialization.",
                        details={"path": str(p), "exception_type": type(exc).__name__},
                    ) from exc
                overlays.append({})
        cfg = load_config_dicts(overlays)
        return cfg, overlay_issues

    def _resolve_skills_config(self, cfg: Any) -> Any:
        """
        解析 skills 配置（优先使用 RuntimeConfig.skills_config，否则使用 SDK config）。

        参数：
        - cfg：已加载的 SDK 配置对象

        返回：
        - 归一化后的 skills_config
        """
        if self._config.skills_config is not None:
            return _normalize_skills_config_for_skills_runtime(self._config.skills_config)
        else:
            return cfg.skills

    def _build_backend(self, *, mode: RuntimeMode, cfg: Any) -> Any:
        """
        构建 ChatBackend 实例。

        参数：
        - mode：bridge 或 sdk_native
        - cfg：已加载的 SDK 配置对象

        返回：
        - ChatBackend 实例
        """
        if self._config.sdk_backend is not None:
            # 离线/测试注入：允许用 FakeChatBackend 等驱动真实 Agent loop，产出完整证据链。
            return self._config.sdk_backend
        elif mode == "bridge":
            if self._config.agently_agent is None:
                raise ValueError("RuntimeConfig.agently_agent is required when mode='bridge'")
            from .adapters.agently_backend import (
                AgentlyBackendConfig,
                AgentlyChatBackend,
                build_openai_compatible_requester_factory,
            )

            requester_factory = build_openai_compatible_requester_factory(agently_agent=self._config.agently_agent)
            return AgentlyChatBackend(config=AgentlyBackendConfig(requester_factory=requester_factory))
        else:
            from skills_runtime.llm.openai_chat import OpenAIChatCompletionsBackend

            return OpenAIChatCompletionsBackend(cfg.llm)

    def _build_skills_manager(self, *, workspace_root: Path, skills_config: Any) -> SkillsManager:
        """
        构建 SkillsManager 实例。

        参数：
        - workspace_root：工作区根目录
        - skills_config：归一化后的 skills 配置

        返回：
        - SkillsManager 实例
        """
        return SkillsManager(
            workspace_root=workspace_root,
            skills_config=skills_config,
            in_memory_registry=self._config.in_memory_skills or {},
        )

    def _init_state(self, *, mode: RuntimeMode) -> _SdkInitState:
        """
        初始化 bridge/sdk_native 的共享资源（backend + SkillsManager）。

        参数：
        - mode：bridge 或 sdk_native
        """

        workspace_root = normalize_workspace_root(self._config.workspace_root)
        config_paths = [Path(p).expanduser().resolve() for p in self._config.sdk_config_paths]

        cfg, overlay_issues = self._load_sdk_config(config_paths)
        skills_cfg = self._resolve_skills_config(cfg)
        backend = self._build_backend(mode=mode, cfg=cfg)
        shared_skills_manager = self._build_skills_manager(workspace_root=workspace_root, skills_config=skills_cfg)

        scan_issues: List[FrameworkIssue] = []
        try:
            report = shared_skills_manager.scan()
        except Exception as exc:
            log_suppressed_exception(
                context="skills_manager_scan",
                exc=exc,
                extra={"workspace_root": str(workspace_root)},
            )
            scan_issues.append(
                FrameworkIssue(
                    code="SKILL_SCAN_EXCEPTION",
                    message="Skills scan raised exception during Runtime initialization.",
                    details={"workspace_root": str(workspace_root), "exception_type": type(exc).__name__},
                )
            )
            if self._config.preflight_mode == "error":
                raise FrameworkError(
                    code="SKILL_SCAN_EXCEPTION",
                    message="Skills scan raised exception during Runtime initialization.",
                    details={"workspace_root": str(workspace_root), "exception_type": type(exc).__name__},
                ) from exc
            report = None

        if report is not None and getattr(report, "errors", None):
            errors = list(getattr(report, "errors", []) or [])
            scan_issues.append(
                FrameworkIssue(
                    code="SKILL_SCAN_FAILED",
                    message="Skills scan reported errors during Runtime initialization.",
                    details={"errors": errors},
                )
            )
            if self._config.preflight_mode == "error":
                raise FrameworkError(
                    code="SKILL_SCAN_FAILED",
                    message="Skills scan failed during Runtime initialization.",
                    details={"errors": errors},
                )

        return _SdkInitState(
            workspace_root=workspace_root,
            config_paths=config_paths,
            skills_config=skills_cfg,
            skills_config_overlay_issues=list(overlay_issues),
            skills_scan_issues=list(scan_issues),
            backend=backend,
            shared_skills_manager=shared_skills_manager,
        )


def _extract_model_override(llm_config: Optional[Dict[str, Any]]) -> Optional[str]:
    """
    从 llm_config 中提取 model 覆写值。

    约束：
    - 本期仅识别 `model` 字段；
    - 空字符串/全空白视为"未设置"。
    """

    if not isinstance(llm_config, dict):
        return None
    raw = llm_config.get("model")
    if not isinstance(raw, str):
        return None
    model = raw.strip()
    return model or None


def _extract_tool_choice_override(llm_config: Optional[Dict[str, Any]]) -> Optional[Any]:
    """
    从 llm_config 中提取 tool_choice 覆写值。

    约束：
    - 仅识别 `tool_choice` 字段；
    - 值必须为 string 或 dict；
    - 必须可 JSON 序列化（JSON-able），否则 fail-closed 抛异常。
    """

    if not isinstance(llm_config, dict):
        return None

    raw = llm_config.get("tool_choice")
    if raw is None:
        return None

    tool_choice: Any
    if isinstance(raw, str):
        v = raw.strip()
        tool_choice = v or None
    elif isinstance(raw, dict):
        tool_choice = raw
    else:
        return None

    if tool_choice is None:
        return None

    import json

    try:
        json.dumps(tool_choice)
    except TypeError as exc:
        raise ValueError("llm_config.tool_choice must be JSON-serializable") from exc

    return tool_choice


def _extract_response_format_override(llm_config: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    从 llm_config 中提取 response_format 覆写值。

    约束：
    - 仅识别 `response_format` 字段；
    - 值必须为 dict；
    - 必须可 JSON 序列化（JSON-able），否则 fail-closed 抛异常。
    """

    if not isinstance(llm_config, dict):
        return None

    raw = llm_config.get("response_format")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None

    import json

    try:
        json.dumps(raw)
    except TypeError as exc:
        raise ValueError("llm_config.response_format must be JSON-serializable") from exc

    return dict(raw)


def _clone_request_with_field_update(
    request: ChatRequest,
    *,
    field_name: str,
    value: Any,
    dataclasses_context: str,
    clone_context: str,
) -> ChatRequest:
    """
    以“安全复制 + 单字段覆写”的方式构造转发 request。

    约束：
    - 覆写必须真实生效，不能在 clone 失败后静默回退原 request；
    - 支持 dict / dataclass / pydantic(v1/v2) 常见形态；
    - 若对象暴露了 clone 能力但全部失败，必须 fail-closed 抛异常。
    """

    if isinstance(request, dict):
        forwarded = dict(request)
        forwarded[field_name] = value
        return forwarded

    try:
        import dataclasses

        if dataclasses.is_dataclass(request):
            return dataclasses.replace(request, **{field_name: value})  # type: ignore[type-var,call-overload]
    except Exception as exc:
        log_suppressed_exception(
            context=dataclasses_context,
            exc=exc,
            extra={"target_field": field_name},
        )

    clone_exc: Optional[Exception] = None
    if hasattr(request, "model_copy"):
        try:
            return request.model_copy(update={field_name: value})
        except Exception as exc:
            log_suppressed_exception(
                context=clone_context,
                exc=exc,
                extra={"method": "model_copy", "target_field": field_name},
            )
            clone_exc = exc
    if hasattr(request, "copy"):
        try:
            return request.copy(update={field_name: value})
        except Exception as exc:
            log_suppressed_exception(
                context=clone_context,
                exc=exc,
                extra={"method": "copy", "target_field": field_name},
            )
            clone_exc = exc

    if clone_exc is not None:
        raise RuntimeError(f"request 对象无法安全覆写字段: {field_name}") from clone_exc

    raise TypeError(
        f"request 对象不支持 {field_name} 覆写：既非 dict，也不支持 dataclasses.replace / model_copy / copy"
    )


class _ModelOverrideBackend:
    """
    ChatBackend 薄代理：仅覆写 request.model，然后委托给底层 backend。

    说明：
    - 该包装仅在 per-run 创建 Agent 时生效（不修改 runtime-wide backend 实例）；
    - 不强依赖 request 的具体实现（pydantic v1/v2 / dict / 普通对象 best-effort 兼容）。
    """

    def __init__(self, *, backend: ChatBackendProtocol, model: str) -> None:
        self._backend: ChatBackendProtocol = backend
        self._model: str = model

    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator[ChatStreamEvent, None]:
        """
        覆写 request.model 并转发 `stream_chat`。

        参数：
        - request：上游 SDK 生成的 ChatRequest（或兼容对象）
        """

        forwarded = _clone_request_with_field_update(
            request,
            field_name="model",
            value=self._model,
            dataclasses_context="model_override_dataclasses_replace",
            clone_context="model_copy_override",
        )

        async for ev in self._backend.stream_chat(forwarded):
            yield ev


class _ToolChoiceOverrideBackend:
    """
    ChatBackend 薄代理：仅覆写 request.extra["tool_choice"]，然后委托给底层 backend。

    说明：
    - 覆写以"拷贝 + 更新"为主，避免修改上游 request 对象的原始 extra 引用；
    - 不强依赖 request 的具体实现（pydantic v1/v2 / dict / 普通对象 best-effort 兼容）。
    """

    def __init__(self, *, backend: ChatBackendProtocol, tool_choice: Any) -> None:
        self._backend: ChatBackendProtocol = backend
        self._tool_choice: Any = tool_choice

    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator[ChatStreamEvent, None]:
        """
        覆写 request.extra["tool_choice"] 并转发 `stream_chat`。

        参数：
        - request：上游 SDK 生成的 ChatRequest（或兼容对象）
        """

        raw_extra = getattr(request, "extra", None)
        extra = dict(raw_extra) if isinstance(raw_extra, dict) else {}
        extra["tool_choice"] = self._tool_choice
        forwarded = _clone_request_with_field_update(
            request,
            field_name="extra",
            value=extra,
            dataclasses_context="tool_choice_override_dataclasses_replace",
            clone_context="tool_choice_override",
        )

        async for ev in self._backend.stream_chat(forwarded):
            yield ev


class _ResponseFormatOverrideBackend:
    """
    ChatBackend 薄代理：仅覆写 request.response_format，然后委托给底层 backend。

    说明：
    - 覆写以"拷贝 + 更新"为主，避免修改上游 request 对象的原始 response_format 引用；
    - 不强依赖 request 的具体实现（pydantic v1/v2 / dict / 普通对象 best-effort 兼容）。
    """

    def __init__(self, *, backend: ChatBackendProtocol, response_format: Dict[str, Any]) -> None:
        self._backend: ChatBackendProtocol = backend
        self._response_format: Dict[str, Any] = dict(response_format)

    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator[ChatStreamEvent, None]:
        """
        覆写 request.response_format 并转发 `stream_chat`。

        参数：
        - request：上游 SDK 生成的 ChatRequest（或兼容对象）
        """

        forwarded = _clone_request_with_field_update(
            request,
            field_name="response_format",
            value=dict(self._response_format),
            dataclasses_context="response_format_override_dataclasses_replace",
            clone_context="response_format_override",
        )

        async for ev in self._backend.stream_chat(forwarded):
            yield ev


class _UsageTapBackend:
    """
    ChatBackend 薄代理：通过 request.extra 注入 usage sink，best-effort 收集 bridge usage。

    说明：
    - 不修改上游 SDK/Agently；
    - request.extra 中的回调不会透传到 wire payload（Agently backend 会过滤 callable）；
    - 若底层 backend 自己能产出 `llm_usage` ChatStreamEvent，本层也会被动收集。
    """

    def __init__(self, *, backend: ChatBackendProtocol) -> None:
        self._backend: ChatBackendProtocol = backend
        self._usage_payloads: List[Dict[str, Any]] = []

    def _capture_usage(self, payload: Any) -> None:
        """记录一次 usage 摘要（fail-open；仅保留 dict 载荷）。"""

        if isinstance(payload, dict):
            self._usage_payloads.append(dict(payload))

    def drain_usage_payloads(self) -> List[Dict[str, Any]]:
        """取出并清空当前 run 累积的 usage 载荷。"""

        out = list(self._usage_payloads)
        self._usage_payloads.clear()
        return out

    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator[ChatStreamEvent, None]:
        """注入 `_caprt_usage_sink` 后转发到底层 backend。"""

        forwarded = _clone_request_with_extra(
            request,
            lambda extra: _merge_usage_sink(extra=extra, sink=self._capture_usage),
        )
        async for ev in self._backend.stream_chat(forwarded):
            if getattr(ev, "type", None) == "llm_usage":
                payload = getattr(ev, "payload", None)
                if isinstance(payload, dict):
                    self._capture_usage(payload)
            yield ev


class _AgentUsageEventBridge:
    """
    Agent 薄代理：在底层未主动发出 `llm_usage` 时，补发 bridge 收集到的 usage AgentEvent。
    """

    def __init__(self, *, agent: Any, usage_bridge_backend: _UsageTapBackend) -> None:
        self._agent = agent
        self._usage_bridge_backend = usage_bridge_backend

    async def run_stream_async(
        self,
        task: str,
        *,
        run_id: Optional[str] = None,
        initial_history: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[AgentEvent]:
        """
        转发 SDK Agent 事件流；若未见上游 `llm_usage`，在流结束后补发 bridge usage 事件。
        """

        saw_llm_usage = False
        last_run_id = run_id or ""
        last_turn_id: Optional[str] = None

        async for ev in self._agent.run_stream_async(task, run_id=run_id, initial_history=initial_history):
            if ev.type == "llm_usage":
                saw_llm_usage = True
            if isinstance(ev.run_id, str) and ev.run_id:
                last_run_id = ev.run_id
            if isinstance(ev.turn_id, str) and ev.turn_id:
                last_turn_id = ev.turn_id
            yield ev

        if saw_llm_usage:
            self._usage_bridge_backend.drain_usage_payloads()
            return

        for payload in self._usage_bridge_backend.drain_usage_payloads():
            yield AgentEvent(
                type="llm_usage",
                timestamp=_now_rfc3339(),
                run_id=last_run_id,
                turn_id=last_turn_id,
                payload=dict(payload),
            )


def _now_rfc3339() -> str:
    """生成 UTC RFC3339 时间戳（秒级 suffices for synthetic llm_usage events）。"""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _merge_usage_sink(*, extra: Dict[str, Any], sink: Any) -> Dict[str, Any]:
    """
    合并 `_caprt_usage_sink` 回调，保留已有 sink 并保证两者都被调用。
    """

    merged = dict(extra or {})
    previous = merged.get("_caprt_usage_sink")

    def _combined(payload: Any) -> None:
        sink(payload)
        if callable(previous):
            previous(payload)

    merged["_caprt_usage_sink"] = _combined
    return merged


def _clone_request_with_extra(request: Any, update_extra: Any) -> Any:
    """
    以"拷贝 + 覆写 extra"的方式构造转发 request（兼容 dict/dataclass/pydantic）。
    """

    if isinstance(request, dict):
        forwarded = dict(request)
        raw_extra = forwarded.get("extra")
        extra = dict(raw_extra) if isinstance(raw_extra, dict) else {}
        forwarded["extra"] = update_extra(extra)
        return forwarded

    raw_extra = getattr(request, "extra", None)
    extra = dict(raw_extra) if isinstance(raw_extra, dict) else {}
    updated_extra = update_extra(extra)

    replaced = False
    forwarded = request
    clone_exc: Optional[Exception] = None
    try:
        import dataclasses

        if dataclasses.is_dataclass(request):
            forwarded = dataclasses.replace(request, extra=updated_extra)  # type: ignore[type-var,assignment]
            replaced = True
    except Exception as exc:
        log_suppressed_exception(
            context="clone_request_with_extra_dataclasses_replace",
            exc=exc,
            extra={"target_field": "extra"},
        )
        replaced = False

    if not replaced:
        if hasattr(request, "model_copy"):
            try:
                forwarded = request.model_copy(update={"extra": updated_extra})
                replaced = True
            except Exception as exc:
                log_suppressed_exception(
                    context="clone_request_with_extra_model_copy",
                    exc=exc,
                    extra={"target_field": "extra"},
                )
                replaced = False
                clone_exc = exc
        if not replaced and hasattr(request, "copy"):
            try:
                forwarded = request.copy(update={"extra": updated_extra})
                replaced = True
            except Exception as exc:
                log_suppressed_exception(
                    context="clone_request_with_extra_copy",
                    exc=exc,
                    extra={"target_field": "extra"},
                )
                replaced = False
                clone_exc = exc

    if not replaced:
        if clone_exc is not None:
            raise RuntimeError("request 对象无法安全覆写 extra 字段") from clone_exc
        raise TypeError("request 对象不支持 extra 覆写：既非 dict，也不支持 dataclasses.replace / model_copy / copy")

    return forwarded


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
      以便"warn 模式可继续跑、error 模式可 fail-closed"由 preflight gate 决定，而不是初始化期直接崩溃。

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
    在调用上游 `load_config_dicts()` 前，对 overlay 做"最小清洗"，避免未知字段导致初始化期直接崩溃。

    说明：
    - 上游 `AgentSdkConfig/AgentSdkSkillsConfig` 默认 `extra=forbid`，因此 overlay 内出现未知字段会直接抛校验异常；
    - 本仓需要在 preflight gate 中把问题以 `FrameworkIssue` 可观测化，并允许 warn 模式继续执行。

    当前清洗范围（最小集合，覆盖本仓离线回归用例）：
    - `skills.roots`：历史字段，产生 `SKILL_CONFIG_LEGACY_ROOTS_UNSUPPORTED` 并移除；
    - `skills.scan` 下未知字段：产生 `SKILL_CONFIG_UNKNOWN_SCAN_OPTION` 并移除未知 key。
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
            # overlay 的目标是"不让初始化期直接崩"，因此这里做 best-effort：丢弃 spaces 并把原因写入 issues。
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
