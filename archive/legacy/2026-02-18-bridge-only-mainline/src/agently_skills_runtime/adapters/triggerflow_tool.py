"""
TriggerFlow tool：`triggerflow_run_flow`。

目标：
- 让 Skills Runtime SDK 的 LLM 能以 tool 形式触发 Agently TriggerFlow flow（“元编排”）。
- 默认必须走 approvals（防止模型绕过业务护栏直接触发流程）。

重要工程约束（必须遵守）：
- SDK ToolRegistry 的 tool handler 是同步函数，无法在 handler 内 `await ApprovalProvider`；
  因此此处 approvals 必须通过 `HumanIOProvider.request_human_input(...)` 实现（同步交互）。
- 审批证据链必须写入 WAL（`approval_requested/approval_decided`），并能被 NodeReport 聚合。

对齐规格：
- `docs/specs/engineering-spec/02_Technical_Design/TOOLS_BUILTINS.md`
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Protocol, Tuple

from agent_sdk.core.contracts import AgentEvent
from agent_sdk.tools.protocol import ToolCall, ToolResult, ToolSpec
from agent_sdk.tools.registry import ToolExecutionContext


class TriggerFlowRunner(Protocol):
    """
    TriggerFlowRunner：由宿主注入的 flow 执行器。

    约束：
    - bridge 层不得 import/调用 TriggerFlow 私有执行细节；
    - runner 必须提供同步方法 `run_flow`（tool handler 同步约束）。
    """

    def run_flow(
        self,
        *,
        flow_name: str,
        input: Any = None,
        timeout_sec: Optional[float] = None,
        wait_for_result: bool = True,
    ) -> Any:
        """
        执行一个 flow 并返回结果。

        参数：
        - `flow_name`：flow 标识
        - `input`：输入 payload（任意 JSONable；不应在审批事件中落明文）
        - `timeout_sec`：超时秒数；None 表示由 runner 自行决定
        - `wait_for_result`：是否等待结果（允许 fire-and-forget 的 runner）
        """

        ...


def _now_rfc3339() -> str:
    """返回 RFC3339 UTC 时间字符串（以 Z 结尾）。"""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_json_hash(obj: Any) -> Tuple[Optional[int], Optional[str]]:
    """
    为对象生成“稳定的体积与 hash”（用于审批摘要，不落明文）。

    返回：
    - (bytes_count, sha256_hex)；当不可序列化时返回 (None, None)。
    """

    try:
        raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except Exception:
        return None, None
    return len(raw), hashlib.sha256(raw).hexdigest()


def _summarize_input(input_obj: Any) -> Dict[str, Any]:
    """
    生成 input 的脱敏摘要（用于 approvals details）。

    约束：
    - 不输出 input 明文
    - 尽量提供可审计的形态信息（keys/len/hash）
    """

    bytes_count, sha256_hex = _stable_json_hash(input_obj)
    out: Dict[str, Any] = {"bytes": bytes_count, "sha256": sha256_hex}

    if input_obj is None:
        out["kind"] = "none"
        return out
    if isinstance(input_obj, dict):
        keys = [str(k) for k in input_obj.keys()]
        keys_sorted = sorted(keys)
        out["kind"] = "object"
        out["keys"] = keys_sorted[:50]
        out["keys_truncated"] = len(keys_sorted) > 50
        out["keys_count"] = len(keys_sorted)
        return out
    if isinstance(input_obj, list):
        out["kind"] = "array"
        out["len"] = len(input_obj)
        return out

    out["kind"] = type(input_obj).__name__
    return out


def _normalize_decision_text(text: str) -> str:
    """规范化人类输入文本（用于 approve/deny 判断）。"""

    return (text or "").strip().lower().replace("-", "_")


@dataclass(frozen=True)
class TriggerFlowToolDeps:
    """
    TriggerFlow tool 的依赖注入集合（便于测试）。

    参数：
    - `runner`：宿主注入的 TriggerFlowRunner
    """

    runner: TriggerFlowRunner


def build_triggerflow_run_flow_tool(*, deps: TriggerFlowToolDeps) -> Tuple[ToolSpec, Any]:
    """
    构造 `triggerflow_run_flow` tool（spec + handler）。

    返回：
    - (ToolSpec, handler)
    """

    spec = ToolSpec(
        name="triggerflow_run_flow",
        description="Run an Agently TriggerFlow flow (requires approval).",
        parameters={
            "type": "object",
            "properties": {
                "flow_name": {"type": "string"},
                "input": {},
                "timeout_sec": {"type": "number"},
                "wait_for_result": {"type": "boolean"},
            },
            "required": ["flow_name"],
            "additionalProperties": False,
        },
        requires_approval=True,
    )

    def handler(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        """
        tool handler：审批 → 执行 flow → 返回结果。

        参数：
        - call：工具调用（含 call_id/name/args）
        - ctx：执行上下文（含 wal/human_io/env/redaction）

        返回：
        - ToolResult（统一 envelope）
        """

        args = call.args or {}
        flow_name = args.get("flow_name")
        if not isinstance(flow_name, str) or not flow_name.strip():
            return ToolResult.error_payload(error_kind="validation", stderr="flow_name must be a non-empty string")
        flow_name = flow_name.strip()

        timeout_sec = args.get("timeout_sec")
        if timeout_sec is not None and not isinstance(timeout_sec, (int, float)):
            return ToolResult.error_payload(error_kind="validation", stderr="timeout_sec must be a number")
        timeout_sec_f = float(timeout_sec) if timeout_sec is not None else None

        wait_for_result = args.get("wait_for_result", True)
        if not isinstance(wait_for_result, bool):
            return ToolResult.error_payload(error_kind="validation", stderr="wait_for_result must be a boolean")

        input_obj = args.get("input", None)

        approval_request = {
            "flow_name": flow_name,
            "timeout_sec": timeout_sec_f,
            "wait_for_result": wait_for_result,
            "input_summary": _summarize_input(input_obj),
        }
        approval_key = hashlib.sha256(
            json.dumps({"tool": call.name, "request": approval_request}, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        summary = f"TriggerFlow: run flow '{flow_name}'"

        # 1) approval_requested
        ctx.emit_event(
            AgentEvent(
                type="approval_requested",
                ts=_now_rfc3339(),
                run_id=ctx.run_id,
                payload={
                    "call_id": call.call_id,
                    "tool": call.name,
                    "approval_key": approval_key,
                    "summary": summary,
                    "request": approval_request,
                },
            )
        )

        if ctx.human_io is None:
            # fail-closed：缺 human_io 时禁止执行
            ctx.emit_event(
                AgentEvent(
                    type="approval_decided",
                    ts=_now_rfc3339(),
                    run_id=ctx.run_id,
                    payload={
                        "call_id": call.call_id,
                        "tool": call.name,
                        "decision": "denied",
                        "reason": "no_human_io",
                    },
                )
            )
            return ToolResult.error_payload(
                error_kind="permission",
                stderr="triggerflow_run_flow requires approval but HumanIOProvider is not configured.",
                data={"approval_key": approval_key, "decision": "denied"},
            )

        answer = ctx.human_io.request_human_input(
            call_id=call.call_id,
            question=summary,
            choices=["approve", "deny"],
            context={"tool": call.name, "approval_key": approval_key, "request": approval_request},
            timeout_ms=None,
        )
        norm = _normalize_decision_text(answer)
        approved = norm in ("approve", "approved", "yes", "y", "ok", "allow", "允许", "同意")

        # 2) approval_decided
        ctx.emit_event(
            AgentEvent(
                type="approval_decided",
                ts=_now_rfc3339(),
                run_id=ctx.run_id,
                payload={
                    "call_id": call.call_id,
                    "tool": call.name,
                    "decision": "approved" if approved else "denied",
                    "reason": "human_io",
                    "approval_key": approval_key,
                },
            )
        )

        if not approved:
            return ToolResult.error_payload(
                error_kind="permission",
                stderr="approval denied for triggerflow_run_flow",
                data={"approval_key": approval_key, "decision": "denied"},
            )

        # 3) execute
        try:
            result = deps.runner.run_flow(
                flow_name=flow_name,
                input=input_obj,
                timeout_sec=timeout_sec_f,
                wait_for_result=wait_for_result,
            )
        except Exception as e:  # pragma: no cover（防御性兜底）
            return ToolResult.error_payload(error_kind="unknown", stderr=str(e), data={"flow_name": flow_name})

        # 尽量保持 JSONable；不可序列化时 fallback 为 str
        result_obj: Any = result
        try:
            json.dumps(result_obj, ensure_ascii=False)
        except Exception:
            result_obj = str(result)

        return ToolResult.ok_payload(
            stdout="",
            data={"flow_name": flow_name, "wait_for_result": wait_for_result, "result": result_obj},
        )

    return spec, handler

