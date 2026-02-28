"""
AgentAdapter：AgentSpec 的执行适配器（统一 mock/bridge/sdk_native）。

说明：
- 本仓不实现 skills 引擎；skills 的注入与执行由上游 `skills_runtime` 完成；
- 本适配器负责把 AgentSpec + input 翻译成 SDK Agent 的 task 文本，并驱动事件流执行；
- `Runtime.run_stream()` 的事件转发语义依赖本适配器的流式执行能力。
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from skills_runtime.core.contracts import AgentEvent
from skills_runtime.core.errors import FrameworkIssue

from ..protocol.agent import AgentSpec
from ..protocol.capability import CapabilityResult, CapabilityStatus
from ..protocol.context import ExecutionContext
from ..reporting.node_report import NodeReportBuilder


class AgentAdapter:
    """
    Agent 适配器（Runtime 内部组件）。

    参数：
    - runtime：统一 Runtime 实例（提供 config 与 bridge 执行的内部工厂方法）
    """

    def __init__(self, *, runtime: Any) -> None:
        self._runtime = runtime

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
        - 转发 SDK AgentEvent，并聚合 NodeReport 写入 CapabilityResult.node_report
        """

        mode = str(getattr(self._runtime.config, "mode", "mock"))
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

        handler = getattr(self._runtime.config, "mock_handler", None)
        if handler is None:
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output={"mock": True, "id": spec.base.id, "input_keys": list(input.keys())},
            )

        try:
            out = None
            try:
                out = handler(spec, input, context)
            except TypeError:
                out = handler(spec, input)

            if hasattr(out, "__await__"):
                out = await out

            if isinstance(out, CapabilityResult):
                return out
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output=out)
        except Exception as exc:
            return CapabilityResult(status=CapabilityStatus.FAILED, error=f"mock_handler error: {exc}")

    async def _bridge_execute_stream(
        self, *, spec: AgentSpec, input: Dict[str, Any], context: ExecutionContext
    ) -> AsyncIterator[Union[AgentEvent, CapabilityResult]]:
        """
        真实执行（bridge/sdk_native）：驱动 SDK Agent.run_stream_async 并聚合 NodeReport。
        """

        # preflight gate（生产默认 fail-closed）
        issues: List[FrameworkIssue] = []
        if getattr(self._runtime.config, "preflight_mode", "error") != "off":
            issues = self._runtime._preflight()
        if issues and getattr(self._runtime.config, "preflight_mode", "error") == "error":
            report = self._runtime._build_fail_closed_report(
                run_id=context.run_id,
                status="failed",
                reason="skill_config_error",
                completion_reason="preflight_failed",
                meta={
                    "preflight_mode": "error",
                    "skill_issue": {
                        "code": "SKILL_PREFLIGHT_FAILED",
                        "details": {"issues": [self._runtime._redact_issue(i) for i in issues]},
                    },
                },
            )
            yield CapabilityResult(
                status=CapabilityStatus.FAILED,
                error="Skills preflight failed",
                report=report,
                node_report=report,
                metadata={"skill_issues": [self._runtime._redact_issue(i) for i in issues]},
            )
            return

        task = self._build_task(spec=spec, input=input)
        agent = self._runtime._create_sdk_agent()

        events: List[AgentEvent] = []
        host_meta = self._runtime._get_host_meta(context=context)
        initial_history = host_meta.get("initial_history") if isinstance(host_meta.get("initial_history"), list) else None

        try:
            async for ev in agent.run_stream_async(task, run_id=context.run_id, initial_history=initial_history):
                events.append(ev)
                # 内部旁路：UI events v1 投影（不改变对外 AgentEvent 语义）
                try:
                    self._runtime._emit_agent_event_taps(ev=ev, context=context, capability_id=spec.base.id)
                except Exception:
                    pass
                if getattr(self._runtime.config, "on_event", None) is not None:
                    try:
                        self._runtime._call_callback(
                            self._runtime.config.on_event,
                            ev,
                            {"run_id": context.run_id, "capability_id": spec.base.id},
                        )
                    except Exception:
                        pass
                yield ev
        except Exception as exc:
            report = self._runtime._build_fail_closed_report(
                run_id=context.run_id,
                status="failed",
                reason="engine_error",
                completion_reason="engine_exception",
                meta={"engine_exception": type(exc).__name__},
            )
            yield CapabilityResult(status=CapabilityStatus.FAILED, error=str(exc), report=report, node_report=report)
            return

        report = NodeReportBuilder().build(events=events)
        if issues and getattr(self._runtime.config, "preflight_mode", "error") == "warn":
            report.meta["preflight_mode"] = "warn"
            report.meta["preflight_issues"] = [self._runtime._redact_issue(i) for i in issues]

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

        self._runtime._apply_output_validation(
            final_output=final_output,
            report=report,
            context={"run_id": context.run_id, "capability_id": spec.base.id, "bag": dict(context.bag)},
        )

        status = self._runtime._map_node_status(report)
        yield CapabilityResult(
            status=status,
            output=final_output,
            error=report.reason if status == CapabilityStatus.FAILED else None,
            report=report,
            node_report=report,
            artifacts=list(report.artifacts),
        )

    def _build_task(self, *, spec: AgentSpec, input: Dict[str, Any]) -> str:
        """
        将 AgentSpec + input 转换为 SDK Agent 的 task 文本（结构化拼接）。

        约束：
        - 不做 prompt engineering；
        - 仅做结构化拼接，保证可回归与可诊断。
        """

        parts: List[str] = []

        if spec.system_prompt and str(spec.system_prompt).strip():
            parts.append(f"## 系统指令\n{str(spec.system_prompt).strip()}")

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

        # skills mention（可选）
        mentions = self._build_skill_mentions(spec=spec)
        if mentions:
            parts.append("## 使用以下 Skills\n" + "\n".join(mentions))

        if spec.prompt_template:
            parts.append(str(spec.prompt_template))

        return "\n\n".join(parts)

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
        skills_cfg = getattr(getattr(self._runtime, "_sdk_state", None), "skills_config", None)
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
