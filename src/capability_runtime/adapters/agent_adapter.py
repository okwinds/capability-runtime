"""
AgentAdapter：AgentSpec 的执行适配器（统一 mock/bridge/sdk_native）。

说明：
- 本仓不实现 skills 引擎；skills 的注入与执行由上游 `skills_runtime` 完成；
- 本适配器负责把 AgentSpec + input 翻译成 SDK Agent 的 task 文本，并驱动事件流执行；
- `Runtime.run_stream()` 的事件转发语义依赖本适配器的流式执行能力。
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from skills_runtime.core.contracts import AgentEvent
from skills_runtime.core.errors import FrameworkIssue

from ..logging_utils import log_suppressed_exception
from ..protocol.agent import AgentSpec
from ..protocol.capability import CapabilityResult, CapabilityStatus
from ..protocol.context import ExecutionContext
from ..reporting.node_report import NodeReportBuilder
from ..services import RuntimeServices, map_node_status

# _build_task 使用的 prompt section 常量
_SECTION_SYSTEM = "## 系统指令"
_SECTION_TASK = "## 任务"
_SECTION_INPUT = "## 输入"
_SECTION_OUTPUT_PREFIX = "## 输出要求"
_SECTION_SKILLS = "## 使用以下 Skills"
_RUNTIME_PROMPT_KEY = "_runtime_prompt"
_PROMPT_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ALLOWED_PROMPT_ROLES = {"system", "developer", "user", "assistant", "tool"}
_ALLOWED_PROMPT_PROFILES = {"default_agent", "generation_direct", "structured_transform"}


class _InvalidPromptMessages(ValueError):
    """prompt control envelope 非法。"""


@dataclass(frozen=True)
class _PromptRenderPlan:
    """
    AgentAdapter 内部 prompt 渲染计划。

    字段：
    - mode：三种 prompt rendering strategy 之一；
    - task：传给 SDK Agent.run_stream_async 的 task 文本；
    - prompt_profile：透传给上游 SDK 的 prompt profile；
    - precomposed_messages：最终 provider messages 覆写；
    - evidence：写入 NodeReport.meta 的最小披露摘要。
    """

    mode: str
    task: str
    prompt_profile: Optional[str]
    precomposed_messages: Optional[List[Dict[str, Any]]]
    evidence: Dict[str, Any]


class AgentAdapter:
    """
    Agent 适配器（Runtime 内部组件）。

    参数：
    - services：RuntimeServices（供 adapter 调用的内部服务协议）
    """

    def __init__(self, *, services: RuntimeServices) -> None:
        self._services = services

    async def execute_stream(
        self,
        *,
        spec: AgentSpec,
        input: Dict[str, Any],
        context: ExecutionContext,
    ) -> AsyncIterator[Union[AgentEvent, CapabilityResult]]:
        """
        流式执行 AgentSpec：先 yield AgentEvent（若为真实执行），最后 yield CapabilityResult。

        mock 模式：
        - 不产出中间事件（只产出最终 CapabilityResult）

        bridge/sdk_native 模式：
        - 转发上游 `skills_runtime` 的 `AgentEvent`（事实事件流）；
        - 基于事件流聚合 `NodeReport` 并写入 `CapabilityResult.node_report`（其中 `events_path` 等字段为证据指针，真相源仍为 WAL/events）。

        备注：
        - 每条 `AgentEvent` 也会通过 Runtime 的内部 tap 旁路分发（用于 UI events 投影；不改变对外 `AgentEvent` 转发语义）。
        """

        mode = str(getattr(self._services.config, "mode", "mock"))
        if mode == "mock":
            yield await self._mock_execute(spec=spec, input=input, context=context)
            return

        async for item in self._bridge_execute_stream(spec=spec, input=input, context=context):
            yield item

    async def _mock_execute(self, *, spec: AgentSpec, input: Dict[str, Any], context: ExecutionContext) -> CapabilityResult:
        """
        mock 执行（离线回归）。

        约束：
        - handler 可返回 Any 或 CapabilityResult；
        - handler 支持同步或 async；
        - 异常将转为 FAILED（避免 silent success）。
        """

        handler = getattr(self._services.config, "mock_handler", None)
        if handler is None:
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"mock": True, "id": spec.base.id, "input_keys": list(input.keys())},
            )

        try:
            # 用 inspect.signature 探测参数数量，避免 try/except TypeError 吞掉 handler 内部的 TypeError
            sig = inspect.signature(handler)
            params = sig.parameters
            has_var_positional = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params.values())
            positional_params = [
                p for p in params.values()
                if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ]

            # 决定传入参数数量：
            # - VAR_POSITIONAL：可接受任意数量，传入全部 3 个
            # - 否则：按位置参数数量切片
            all_args = (spec, input, context)
            if has_var_positional:
                call_args = all_args
            elif len(positional_params) >= 3:
                call_args = all_args
            elif len(positional_params) == 2:
                call_args = (spec, input)
            elif len(positional_params) == 1:
                call_args = (spec,)
            else:
                call_args = ()

            is_async_handler = inspect.iscoroutinefunction(handler) or inspect.iscoroutinefunction(
                getattr(handler, "__call__", None)
            )
            if is_async_handler:
                out = handler(*call_args)
            else:
                # 同步 mock_handler 放到 worker thread 执行，避免阻塞当前事件循环，
                # 使 workflow step/loop timeout 等上层护栏仍然有效。
                out = await asyncio.to_thread(handler, *call_args)

            if inspect.isawaitable(out):
                out = await out

            if isinstance(out, CapabilityResult):
                return out
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output=out)
        except asyncio.CancelledError:
            report = self._services.build_fail_closed_report(
                run_id=context.run_id,
                status="incomplete",
                reason="cancelled",
                completion_reason="run_cancelled",
                meta={"capability_id": spec.base.id, "source": "mock_handler"},
            )
            return CapabilityResult(
                status=CapabilityStatus.CANCELLED,
                error="execution cancelled",
                error_code="RUN_CANCELLED",
                report=report,
                node_report=report,
            )
        except Exception as exc:
            report = self._services.build_fail_closed_report(
                run_id=context.run_id,
                status="failed",
                reason="mock_handler_error",
                completion_reason="mock_handler_error",
                meta={"capability_id": spec.base.id, "exception_type": type(exc).__name__},
            )
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"mock_handler error: {exc}",
                error_code="MOCK_HANDLER_ERROR",
                report=report,
                node_report=report,
            )

    async def _bridge_execute_stream(
        self, *, spec: AgentSpec, input: Dict[str, Any], context: ExecutionContext
    ) -> AsyncIterator[Union[AgentEvent, CapabilityResult]]:
        """
        真实执行（bridge/sdk_native）：驱动 SDK Agent.run_stream_async 并聚合 NodeReport。
        """

        try:
            prompt_plan = self._resolve_prompt_render_plan(spec=spec, input=input)
        except _InvalidPromptMessages as exc:
            report = self._services.build_fail_closed_report(
                run_id=context.run_id,
                status="failed",
                reason="invalid_prompt_messages",
                completion_reason="invalid_prompt_messages",
                meta={
                    "capability_id": spec.base.id,
                    "source": "prompt_rendering",
                    "prompt_error": str(exc),
                },
            )
            yield CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=str(exc),
                error_code="INVALID_PROMPT_MESSAGES",
                report=report,
                node_report=report,
            )
            return

        # preflight gate（生产默认 fail-closed）
        issues: List[FrameworkIssue] = []
        if getattr(self._services.config, "preflight_mode", "error") != "off":
            issues = self._services.preflight()
        if issues and getattr(self._services.config, "preflight_mode", "error") == "error":
            report = self._services.build_fail_closed_report(
                run_id=context.run_id,
                status="failed",
                reason="skill_config_error",
                completion_reason="preflight_failed",
                meta={
                    "preflight_mode": "error",
                    "skill_issue": {
                        "code": "SKILL_PREFLIGHT_FAILED",
                        "details": {"issues": [self._services.redact_issue(i) for i in issues]},
                    },
                    **prompt_plan.evidence,
                },
            )
            yield CapabilityResult(
                status=CapabilityStatus.FAILED,
                error="Skills preflight failed",
                error_code="PREFLIGHT_FAILED",
                report=report,
                node_report=report,
                metadata={"skill_issues": [self._services.redact_issue(i) for i in issues]},
            )
            return

        task = prompt_plan.task
        create_agent_kwargs: Dict[str, Any] = {"llm_config": spec.llm_config}
        if prompt_plan.prompt_profile is not None:
            create_agent_kwargs["prompt_profile"] = prompt_plan.prompt_profile
        if prompt_plan.precomposed_messages is not None:
            create_agent_kwargs["precomposed_messages"] = prompt_plan.precomposed_messages
        try:
            agent = self._services.create_sdk_agent(**create_agent_kwargs)
        except Exception as exc:
            report = self._services.build_fail_closed_report(
                run_id=context.run_id,
                status="failed",
                reason="engine_error",
                completion_reason="engine_exception",
                meta={
                    "source": "sdk_agent_create",
                    "engine_exception": type(exc).__name__,
                    **prompt_plan.evidence,
                },
            )
            yield CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=str(exc),
                error_code="ENGINE_ERROR",
                report=report,
                node_report=report,
            )
            return

        events: List[AgentEvent] = []
        host_meta = self._services.get_host_meta(context=context)
        initial_history = host_meta.get("initial_history") if isinstance(host_meta.get("initial_history"), list) else None

        try:
            async for ev in agent.run_stream_async(task, run_id=context.run_id, initial_history=initial_history):
                events.append(ev)
                # 内部旁路：UI events v1 投影（不改变对外 AgentEvent 语义）
                try:
                    self._services.emit_agent_event_taps(ev=ev, context=context, capability_id=spec.base.id)
                except Exception as tap_exc:
                    log_suppressed_exception(
                        context="emit_agent_event_taps",
                        exc=tap_exc,
                        run_id=context.run_id,
                        capability_id=spec.base.id,
                        extra={"event_type": getattr(ev, "type", None)},
                    )
                if getattr(self._services.config, "on_event", None) is not None:
                    try:
                        self._services.call_callback(
                            self._services.config.on_event,
                            ev,
                            {"run_id": context.run_id, "capability_id": spec.base.id},
                        )
                    except Exception as cb_exc:
                        log_suppressed_exception(
                            context="on_event_callback",
                            exc=cb_exc,
                            run_id=context.run_id,
                            capability_id=spec.base.id,
                            extra={"event_type": getattr(ev, "type", None)},
                        )
                yield ev
        except asyncio.CancelledError:
            report = self._services.build_fail_closed_report(
                run_id=context.run_id,
                status="incomplete",
                reason="cancelled",
                completion_reason="run_cancelled",
                meta={"capability_id": spec.base.id, "source": "sdk_agent"},
            )
            self._apply_prompt_evidence(report=report, evidence=prompt_plan.evidence)
            yield CapabilityResult(
                status=CapabilityStatus.CANCELLED,
                error="execution cancelled",
                error_code="RUN_CANCELLED",
                report=report,
                node_report=report,
            )
            return
        except Exception as exc:
            report = self._services.build_fail_closed_report(
                run_id=context.run_id,
                status="failed",
                reason="engine_error",
                completion_reason="engine_exception",
                meta={"engine_exception": type(exc).__name__, **prompt_plan.evidence},
            )
            yield CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=str(exc),
                error_code="ENGINE_ERROR",
                report=report,
                node_report=report,
            )
            return

        report = NodeReportBuilder().build(events=events)
        self._apply_prompt_evidence(report=report, evidence=prompt_plan.evidence)
        if issues and getattr(self._services.config, "preflight_mode", "error") == "warn":
            report.meta["preflight_mode"] = "warn"
            report.meta["preflight_issues"] = [self._services.redact_issue(i) for i in issues]

        if initial_history is not None:
            report.meta["initial_history_injected"] = True
        session_id = host_meta.get("session_id")
        if isinstance(session_id, str) and session_id:
            report.meta["session_id"] = session_id
        host_turn_id = host_meta.get("host_turn_id")
        if isinstance(host_turn_id, str) and host_turn_id:
            report.meta["host_turn_id"] = host_turn_id

        final_output = ""
        for ev in events:
            if ev.type == "run_completed":
                final_output = str(ev.payload.get("final_output") or "")
            if ev.type in ("run_failed", "run_cancelled"):
                final_output = str(ev.payload.get("message") or "")
            if ev.type == "run_waiting_human":
                final_output = str(ev.payload.get("message") or "")

        self._services.apply_output_validation(
            final_output=final_output,
            report=report,
            context={"run_id": context.run_id, "capability_id": spec.base.id, "bag": dict(context.bag)},
            output_schema=spec.output_schema,
        )

        status = map_node_status(report)
        yield CapabilityResult(
            status=status,
            output=final_output,
            error=report.reason if status == CapabilityStatus.FAILED else None,
            report=report,
            node_report=report,
            artifacts=list(report.artifacts),
        )

    def _resolve_prompt_render_plan(self, *, spec: AgentSpec, input: Dict[str, Any]) -> _PromptRenderPlan:
        """
        解析 AgentSpec + run-level `_runtime_prompt`，生成 prompt 渲染计划。

        参数：
        - spec：Agent 声明
        - input：run 输入，其中 `_runtime_prompt` 为保留控制面

        返回：
        - `_PromptRenderPlan`

        异常：
        - `_InvalidPromptMessages`：控制面非法，调用方应 fail-fast。
        """

        envelope_raw = input.get(_RUNTIME_PROMPT_KEY)
        if envelope_raw is None:
            envelope: Dict[str, Any] = {}
        elif isinstance(envelope_raw, dict):
            envelope = dict(envelope_raw)
        else:
            raise _InvalidPromptMessages("_runtime_prompt must be a dict")

        raw_mode = envelope.get("mode") if "mode" in envelope else getattr(spec, "prompt_render_mode", "structured_task")
        if raw_mode is None:
            raw_mode = "structured_task"
        if not isinstance(raw_mode, str) or not raw_mode.strip():
            raise _InvalidPromptMessages("prompt render mode must be a non-empty string")
        mode = raw_mode.strip()
        if mode not in {"structured_task", "direct_task_text", "precomposed_messages"}:
            raise _InvalidPromptMessages(
                "unsupported prompt render mode; allowed: direct_task_text, precomposed_messages, structured_task"
            )

        prompt_profile = envelope.get("profile")
        if prompt_profile is None:
            prompt_profile = getattr(spec, "prompt_profile", None)
        if prompt_profile is not None:
            if not isinstance(prompt_profile, str) or not prompt_profile.strip():
                raise _InvalidPromptMessages("prompt profile must be a non-empty string")
            prompt_profile = prompt_profile.strip()
            if prompt_profile not in _ALLOWED_PROMPT_PROFILES:
                allowed = ", ".join(sorted(_ALLOWED_PROMPT_PROFILES))
                raise _InvalidPromptMessages(f"unsupported prompt profile; allowed: {allowed}")

        trace = envelope.get("trace") if "trace" in envelope else {}
        if trace is None:
            trace = {}
        if not isinstance(trace, dict):
            raise _InvalidPromptMessages("_runtime_prompt.trace must be a dict")
        prompt_hash = trace.get("prompt_hash")
        if prompt_hash is not None:
            if not isinstance(prompt_hash, str) or _PROMPT_HASH_RE.fullmatch(prompt_hash.strip()) is None:
                raise _InvalidPromptMessages("trace.prompt_hash must match sha256:<64 lowercase hex>")
            prompt_hash = prompt_hash.strip()
        composer_version = trace.get("composer_version")
        if composer_version is not None and not isinstance(composer_version, str):
            raise _InvalidPromptMessages("trace.composer_version must be a string")

        if mode == "structured_task":
            business_input = self._strip_runtime_prompt(input)
            task = self._build_task(spec=spec, input=business_input)
            evidence = self._build_prompt_evidence(
                mode=mode,
                prompt_profile=prompt_profile,
                prompt_hash=prompt_hash or _hash_text(task),
                composer_version=composer_version,
                messages=None,
            )
            return _PromptRenderPlan(
                mode=mode,
                task=task,
                prompt_profile=prompt_profile,
                precomposed_messages=None,
                evidence=evidence,
            )

        if mode == "direct_task_text":
            task_text = envelope.get("task_text")
            if not isinstance(task_text, str) or not task_text.strip():
                raise _InvalidPromptMessages("_runtime_prompt.task_text must be a non-empty string")
            task = task_text
            evidence = self._build_prompt_evidence(
                mode=mode,
                prompt_profile=prompt_profile,
                prompt_hash=prompt_hash or _hash_text(task),
                composer_version=composer_version,
                messages=None,
            )
            return _PromptRenderPlan(
                mode=mode,
                task=task,
                prompt_profile=prompt_profile,
                precomposed_messages=None,
                evidence=evidence,
            )

        messages = _validate_precomposed_messages(envelope.get("messages"))
        evidence = self._build_prompt_evidence(
            mode=mode,
            prompt_profile=prompt_profile,
            prompt_hash=prompt_hash or _hash_messages(messages),
            composer_version=composer_version,
            messages=messages,
        )
        return _PromptRenderPlan(
            mode=mode,
            task="",
            prompt_profile=prompt_profile,
            precomposed_messages=messages,
            evidence=evidence,
        )

    def _build_prompt_evidence(
        self,
        *,
        mode: str,
        prompt_profile: Optional[str],
        prompt_hash: str,
        composer_version: Any,
        messages: Optional[List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """
        构造 NodeReport.meta 的 prompt 最小披露摘要。

        参数：
        - mode：prompt render mode
        - prompt_profile：可选 SDK prompt profile
        - prompt_hash：`sha256:<hex>` 摘要
        - composer_version：可选 composer 版本
        - messages：precomposed messages；仅用于 count/roles 摘要
        """

        evidence: Dict[str, Any] = {
            "prompt_render_mode": mode,
            "prompt_hash": prompt_hash,
        }
        if prompt_profile:
            evidence["prompt_profile"] = prompt_profile
        if isinstance(composer_version, str) and composer_version:
            evidence["prompt_composer_version"] = composer_version
        if messages is not None:
            evidence["prompt_messages_count"] = len(messages)
            evidence["prompt_message_roles"] = [str(item["role"]) for item in messages]
        return evidence

    def _strip_runtime_prompt(self, input: Dict[str, Any]) -> Dict[str, Any]:
        """从业务 input 中剥离 runtime prompt 控制面。"""

        if _RUNTIME_PROMPT_KEY not in input:
            return input
        return {k: v for k, v in input.items() if k != _RUNTIME_PROMPT_KEY}

    def _apply_prompt_evidence(self, *, report: Any, evidence: Dict[str, Any]) -> None:
        """把 prompt evidence 写入 NodeReport.meta；兼容测试中的 dict fake report。"""

        meta = getattr(report, "meta", None)
        if isinstance(meta, dict):
            meta.update(evidence)

    def _build_task(self, *, spec: AgentSpec, input: Dict[str, Any]) -> str:
        """
        将 AgentSpec + input 转换为 SDK Agent 的 task 文本（结构化拼接）。

        约束：
        - 不做 prompt engineering；
        - 仅做结构化拼接，保证可回归与可诊断。
        """

        parts: List[str] = []

        if spec.system_prompt and str(spec.system_prompt).strip():
            parts.append(f"{_SECTION_SYSTEM}\n{str(spec.system_prompt).strip()}")

        if spec.base.description:
            parts.append(f"{_SECTION_TASK}\n{spec.base.description}")

        business_input = self._strip_runtime_prompt(input)
        if business_input:
            lines: List[str] = []
            for k, v in business_input.items():
                if isinstance(v, str):
                    lines.append(f"- {k}: {v}")
                else:
                    lines.append(f"- {k}: {json.dumps(v, ensure_ascii=False)}")
            parts.append(f"{_SECTION_INPUT}\n" + "\n".join(lines))

        if spec.output_schema and spec.output_schema.fields:
            parts.append(self._build_output_contract(spec=spec))

        # skills mention（可选）
        mentions = self._build_skill_mentions(spec=spec)
        if mentions:
            parts.append(f"{_SECTION_SKILLS}\n" + "\n".join(mentions))

        if spec.prompt_template:
            parts.append(str(spec.prompt_template))

        return "\n\n".join(parts)

    def _build_output_contract(self, *, spec: AgentSpec) -> str:
        """
        构造结构化输出约束段。

        说明：
        - 这里仍属于提示层约束，但要明确“只返回 JSON object”；
        - 真正的收口由 Runtime 的结构化输出校验负责。
        """

        if spec.output_schema is None:
            return ""

        lines = [
            _SECTION_OUTPUT_PREFIX,
            "请只返回 JSON object，不要 Markdown code fence，不要解释性前后缀。",
            "字段要求：",
        ]
        lines.extend([f"- {name}: {typ}" for name, typ in spec.output_schema.fields.items()])

        required = [str(name) for name in list(spec.output_schema.required or []) if str(name)]
        if required:
            lines.append("必填字段：")
            lines.extend([f"- {name}" for name in required])

        return "\n".join(lines)

    def _build_skill_mentions(self, *, spec: AgentSpec) -> List[str]:
        """
        将 spec.skills 转为 SDK 识别的 mention 文本。

        优先级：
        1) skills_mention_map 显式映射（最稳定）
        2) 从 Runtime bridge 初始化的 skills_config 推断默认 space（尽力而为）
        """

        skills = list(getattr(spec, "skills", []) or [])
        if not skills:
            return []

        mention_map: Dict[str, str] = dict(getattr(spec, "skills_mention_map", {}) or {})

        inferred_prefix: Optional[str] = None
        skills_cfg = getattr(self._services.config, "skills_config", None)
        inferred_prefix = self._infer_space_prefix(skills_cfg)

        out: List[str] = []
        for name in skills:
            if name in mention_map and str(mention_map[name]).strip():
                out.append(str(mention_map[name]).strip())
                continue
            if inferred_prefix:
                out.append(f"${inferred_prefix}.{name}")
        return out

    def _infer_space_prefix(self, skills_cfg: Any) -> Optional[str]:
        """
        从 skills_config 推断 strict mention 的 space 前缀（版本感知）。

        说明：
        - 该逻辑是 best-effort：skills_config 的具体形态由上游决定（dict / pydantic model / dataclass）。
        - 无法推断时返回 None（调用方将不输出 mention）。

        返回值形态：
        - legacy：`[account:domain]`
        - v0.1.5+：`[namespace]`（namespace 允许 `a:b:c` 多段）
        """

        spaces = None
        if isinstance(skills_cfg, dict):
            spaces = skills_cfg.get("spaces")
        else:
            spaces = getattr(skills_cfg, "spaces", None)

        if not isinstance(spaces, list):
            return None

        def _get(obj: Any, key: str) -> Optional[str]:
            if isinstance(obj, dict):
                v = obj.get(key)
            else:
                v = getattr(obj, key, None)
            return str(v).strip() if isinstance(v, str) and str(v).strip() else None

        for sp in spaces:
            namespace = _get(sp, "namespace")
            if namespace:
                return f"[{namespace}]"
            account = _get(sp, "account")
            domain = _get(sp, "domain")
            if account and domain:
                return f"[{account}:{domain}]"
        return None


def _hash_text(text: str) -> str:
    """生成 prompt 文本的 sha256 摘要。"""

    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_messages(messages: List[Dict[str, Any]]) -> str:
    """对 provider messages 做稳定 JSON canonicalization 后生成摘要。"""

    canonical = json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _hash_text(canonical)


def _validate_precomposed_messages(raw: Any) -> List[Dict[str, Any]]:
    """
    校验 host 提供的最终 provider messages。

    约束：
    - 只接受非空 list[dict]；
    - 每条消息必须有合法 role 与字符串 content；
    - 返回浅拷贝，避免后续执行链路修改调用方输入。
    """

    if not isinstance(raw, list):
        raise _InvalidPromptMessages("_runtime_prompt.messages must be a list")
    if not raw:
        raise _InvalidPromptMessages("_runtime_prompt.messages must not be empty")

    out: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise _InvalidPromptMessages(f"_runtime_prompt.messages[{idx}] must be a dict")
        role = item.get("role")
        content = item.get("content")
        if not isinstance(role, str) or role not in _ALLOWED_PROMPT_ROLES:
            raise _InvalidPromptMessages(f"_runtime_prompt.messages[{idx}].role is invalid")
        if not isinstance(content, str):
            raise _InvalidPromptMessages(f"_runtime_prompt.messages[{idx}].content must be a string")
        copied = dict(item)
        copied["role"] = role
        copied["content"] = content
        out.append(copied)
    return out
