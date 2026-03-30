from __future__ import annotations

"""
Runtime UI Events：把底层事件投影为 RuntimeEvent v1（ui-friendly）。

输入（事实源）：
- skills_runtime.AgentEvent（tool/approval/run_* 等）
- WorkflowStreamEvent（workflow.* 轻量事件 dict）
- CapabilityResult（终态）

输出：
- RuntimeEvent v1（Envelope + path + level）

约束：
- 不把 UI events 当作审计真相源；证据链指针只引用 WAL/NodeReport/tool evidence。
- 最小披露：不输出 tool args/outputs 明文，只输出摘要（top_keys/bytes/sha256）。
"""

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from skills_runtime.core.contracts import AgentEvent

from ..host_protocol import project_host_runtime_data
from ..logging_utils import log_suppressed_exception
from ..protocol.capability import CapabilityResult, CapabilityStatus
from ..types import NodeReport
from ..utils.usage import extract_usage_metrics
from .v1 import Evidence, PathSegment, RuntimeEvent, StreamLevel


_SCHEMA = "capability-runtime.runtime_event.v1"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _summarize_dict(obj: Any) -> Optional[Dict[str, Any]]:
    """
    将 dict 归一为最小披露摘要。

    返回：
    - None：无法摘要（非 dict）
    - dict：包含 top_keys/bytes/sha256（不含明文 values）
    """

    if not isinstance(obj, dict):
        return None
    try:
        raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except Exception as exc:
        log_suppressed_exception(
            context="summarize_dict_json_encode",
            exc=exc,
            extra={"obj_type": type(obj).__name__},
        )
        raw = "{}"
    return {
        "top_keys": sorted([str(k) for k in obj.keys()])[:50],
        "bytes": len(raw.encode("utf-8")),
        "sha256": _sha256_text(raw),
    }


def _normalize_terminal_status(status: CapabilityStatus) -> str:
    if status == CapabilityStatus.SUCCESS:
        return "completed"
    if status == CapabilityStatus.FAILED:
        return "failed"
    if status == CapabilityStatus.CANCELLED:
        return "cancelled"
    return "pending"


@dataclass
class _AgentCtx:
    run_id: str
    capability_id: str
    workflow_id: Optional[str] = None
    workflow_instance_id: Optional[str] = None
    step_id: Optional[str] = None
    branch_id: Optional[str] = None
    # outer → inner 的嵌套链提示（best-effort）；若存在则优先用于生成 path
    wf_frames: Optional[List[Dict[str, str]]] = None


class RuntimeUIEventProjector:
    """
    投影器（per-run）。

    说明：
    - `seq`/`rid` 在投影器内生成：单 run 单调递增；
    - `rid` 默认等于 `seq` 的字符串（满足断线续传 exclusive 语义的最小实现）。
    """

    def __init__(self, *, run_id: str, level: StreamLevel) -> None:
        self._run_id = run_id
        self._level = level
        self._seq = 0
        self._skill_mention_to_locator: Dict[str, str] = {}
        self._skill_name_to_locator: Dict[str, str] = {}
        # call_id -> origin path（用于“哪来哪去”，避免 tool/approval 生命周期事件归属漂移）
        self._call_origin_path: Dict[str, List[PathSegment]] = {}
        # approvals 可能缺 call_id：best-effort 用 step_id 恢复归属（见 docs/specs/runtime-ui-events-v1.md）
        self._step_scope_to_call_id: Dict[str, str] = {}
        self._step_scope_tool_to_call_id: Dict[tuple[str, str], str] = {}

    def _step_scope_key(self, *, ctx: _AgentCtx) -> Optional[str]:
        """
        生成“step 作用域键”（best-effort 消歧）。

        说明：
        - approvals 的 step_id 关联是 best-effort：仅在 run 内临时使用；
        - 为避免多个 workflow/agent 复用相同 step_id 造成互相污染，这里把 workflow/branch/agent 信息纳入 key；
        - 若 ctx 无 step_id，返回 None。
        """

        step_id = str(ctx.step_id or "").strip()
        if not step_id:
            return None
        workflow_scope = str(ctx.workflow_instance_id or ctx.workflow_id or "").strip()
        branch_scope = str(ctx.branch_id or "").strip()
        agent_scope = str(ctx.capability_id or "").strip()
        return f"{workflow_scope}::{branch_scope}::{agent_scope}::{step_id}"

    def _best_effort_call_id_from_step(self, *, ctx: _AgentCtx, tool: str) -> Optional[str]:
        """
        best-effort 通过 step_id（可选加 tool）恢复 call_id。

        说明：
        - 优先用 `(step_id, tool)` 精确匹配；
        - 再回退到 `step_id` 的最近一次 call_id；
        - 若 ctx 无 step_id 或未命中，返回 None。
        """

        step_scope_key = self._step_scope_key(ctx=ctx)
        if step_scope_key is None:
            return None
        tool = str(tool or "").strip()
        if tool:
            call_id = self._step_scope_tool_to_call_id.get((step_scope_key, tool))
            if call_id:
                return call_id
        return self._step_scope_to_call_id.get(step_scope_key)

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _base_path(self, *, ctx: Optional[_AgentCtx] = None) -> List[PathSegment]:
        segs: List[PathSegment] = [PathSegment(kind="run", id=self._run_id)]
        if ctx is None:
            return segs
        if ctx.wf_frames:
            for frame in ctx.wf_frames:
                wf_id = frame.get("workflow_id")
                wf_inst = frame.get("workflow_instance_id") or wf_id
                if wf_inst:
                    segs.append(
                        PathSegment(
                            kind="workflow",
                            id=wf_inst,
                            instance_id=wf_inst,
                            ref={"kind": "workflow", "id": wf_id} if wf_id else None,
                        )
                    )
                step_id = frame.get("step_id")
                if step_id:
                    segs.append(PathSegment(kind="step", id=step_id))
                branch_id = frame.get("branch_id")
                if branch_id:
                    segs.append(PathSegment(kind="branch", id=branch_id))
        else:
            if ctx.workflow_id:
                # legacy：仍提供 ref，便于消费端按逻辑 workflow_id 过滤
                segs.append(
                    PathSegment(
                        kind="workflow",
                        id=ctx.workflow_instance_id or ctx.workflow_id,
                        instance_id=ctx.workflow_instance_id or ctx.workflow_id,
                        ref={"kind": "workflow", "id": ctx.workflow_id},
                    )
                )
            if ctx.step_id:
                segs.append(PathSegment(kind="step", id=ctx.step_id))
            if ctx.branch_id:
                segs.append(PathSegment(kind="branch", id=ctx.branch_id))
        if ctx.capability_id:
            segs.append(PathSegment(kind="agent", id=ctx.capability_id))
        return segs

    def _emit(
        self,
        *,
        type: str,
        path: List[PathSegment],
        data: Dict[str, Any],
        evidence: Optional[Evidence] = None,
    ) -> RuntimeEvent:
        seq = self._next_seq()
        return RuntimeEvent(
            schema=_SCHEMA,
            type=type,
            run_id=self._run_id,
            seq=seq,
            ts_ms=_now_ms(),
            level=self._level,
            path=path,
            data=dict(data or {}),
            rid=str(seq),
            evidence=evidence,
        )

    def start(self) -> List[RuntimeEvent]:
        return [self._emit(type="run.status", path=self._base_path(), data={"status": "running"})]

    def heartbeat(self) -> RuntimeEvent:
        return self._emit(type="heartbeat", path=self._base_path(), data={})

    def error(self, *, kind: str, message: str, data: Optional[Dict[str, Any]] = None) -> RuntimeEvent:
        payload: Dict[str, Any] = {"kind": str(kind), "message": str(message)}
        if data:
            for k, v in dict(data).items():
                if k in {"kind", "message"}:
                    continue
                payload[k] = v
        return self._emit(type="error", path=self._base_path(), data=payload)

    def on_workflow_event(self, ev: Dict[str, Any]) -> List[RuntimeEvent]:
        typ = str(ev.get("type") or "")
        run_id = str(ev.get("run_id") or "")
        if run_id and run_id != self._run_id:
            return []

        workflow_id = str(ev.get("workflow_id") or "").strip() or None
        workflow_instance_id = str(ev.get("workflow_instance_id") or "").strip() or None
        step_id = str(ev.get("step_id") or "").strip() or None

        out: List[RuntimeEvent] = []
        if typ == "workflow.started" and workflow_id:
            wf_seg = PathSegment(
                kind="workflow",
                id=workflow_instance_id or workflow_id,
                instance_id=workflow_instance_id or workflow_id,
                ref={"kind": "workflow", "id": workflow_id},
            )
            out.append(
                self._emit(
                    type="node.started",
                    path=[PathSegment(kind="run", id=self._run_id), wf_seg],
                    data={"node_kind": "workflow", "workflow_id": workflow_id, "workflow_instance_id": workflow_instance_id},
                )
            )
            if self._level != StreamLevel.LITE:
                out.append(
                    self._emit(
                        type="node.phase",
                        path=[PathSegment(kind="run", id=self._run_id), wf_seg],
                        data={"phase": "RUNNING"},
                    )
                )
            return out

        if typ == "workflow.step.started" and workflow_id and step_id:
            wf_seg = PathSegment(
                kind="workflow",
                id=workflow_instance_id or workflow_id,
                instance_id=workflow_instance_id or workflow_id,
                ref={"kind": "workflow", "id": workflow_id},
            )
            path = [
                PathSegment(kind="run", id=self._run_id),
                wf_seg,
                PathSegment(kind="step", id=step_id),
            ]
            out.append(
                self._emit(
                    type="node.started",
                    path=path,
                    data={"node_kind": "step", "workflow_id": workflow_id, "workflow_instance_id": workflow_instance_id, "step_id": step_id},
                )
            )
            if self._level != StreamLevel.LITE:
                out.append(self._emit(type="node.phase", path=path, data={"phase": "RUNNING"}))
            return out

        if typ == "workflow.step.finished" and workflow_id and step_id:
            status_raw = str(ev.get("status") or "").strip()
            status = status_raw if status_raw in {"success", "failed", "pending", "cancelled"} else "pending"
            wf_seg = PathSegment(
                kind="workflow",
                id=workflow_instance_id or workflow_id,
                instance_id=workflow_instance_id or workflow_id,
                ref={"kind": "workflow", "id": workflow_id},
            )
            path = [
                PathSegment(kind="run", id=self._run_id),
                wf_seg,
                PathSegment(kind="step", id=step_id),
            ]
            if self._level != StreamLevel.LITE:
                out.append(self._emit(type="node.phase", path=path, data={"phase": "DONE"}))
            out.append(
                self._emit(
                    type="node.finished",
                    path=path,
                    data={"status": status, "workflow_id": workflow_id, "workflow_instance_id": workflow_instance_id, "step_id": step_id},
                )
            )
            return out

        if typ == "workflow.finished" and workflow_id:
            status_raw = str(ev.get("status") or "").strip()
            status = status_raw if status_raw in {"success", "failed", "pending", "cancelled"} else "pending"
            wf_seg = PathSegment(
                kind="workflow",
                id=workflow_instance_id or workflow_id,
                instance_id=workflow_instance_id or workflow_id,
                ref={"kind": "workflow", "id": workflow_id},
            )
            path = [PathSegment(kind="run", id=self._run_id), wf_seg]
            if self._level != StreamLevel.LITE:
                out.append(self._emit(type="node.phase", path=path, data={"phase": "DONE"}))
            out.append(
                self._emit(
                    type="node.finished",
                    path=path,
                    data={"status": status, "workflow_id": workflow_id, "workflow_instance_id": workflow_instance_id},
                )
            )
            return out

        return []

    def on_agent_event(self, ev: AgentEvent, *, ctx: _AgentCtx) -> List[RuntimeEvent]:
        if self._level == StreamLevel.LITE:
            return []
        if ev.run_id != self._run_id:
            return []

        out: List[RuntimeEvent] = []
        base_path = self._base_path(ctx=ctx)

        if self._level == StreamLevel.RAW:
            out.append(
                self._emit(
                    type="raw.agent_event",
                    path=base_path,
                    data={
                        "agent_event_type": str(ev.type),
                        "payload_summary": _summarize_dict(ev.payload) or {},
                    },
                )
            )

        if ev.type == "skill_injected":
            locator = ev.payload.get("skill_locator")
            skill_name = ev.payload.get("skill_name")
            mention_text = ev.payload.get("mention_text")
            if isinstance(locator, str) and locator.strip():
                if isinstance(mention_text, str) and mention_text.strip():
                    self._skill_mention_to_locator[mention_text.strip()] = locator.strip()
                if isinstance(skill_name, str) and skill_name.strip():
                    self._skill_name_to_locator[skill_name.strip()] = locator.strip()
            return out

        if ev.type == "run_started":
            out.append(self._emit(type="node.started", path=base_path, data={"node_kind": "agent"}))
            out.append(self._emit(type="node.phase", path=base_path, data={"phase": "THINKING"}))
            return out

        if ev.type == "llm_usage":
            out.append(self._emit(type="metrics", path=base_path, data=extract_usage_metrics(ev.payload)))
            return out

        if ev.type in ("run_completed", "run_failed", "run_cancelled", "run_waiting_human"):
            if ev.type == "run_completed":
                status = "success"
                # best-effort：run_* 事件出现后通常意味着进入“产出/收敛”阶段
                out.append(self._emit(type="node.phase", path=base_path, data={"phase": "REPORTING"}))
                out.append(self._emit(type="node.phase", path=base_path, data={"phase": "DONE"}))
                out.append(self._emit(type="node.finished", path=base_path, data={"status": status}))
                return out

            if ev.type == "run_failed":
                status = "failed"
                data: Dict[str, Any] = {"status": status}
                error_kind = ev.payload.get("error_kind")
                if isinstance(error_kind, str) and error_kind.strip():
                    data["error_kind"] = error_kind.strip()
                out.append(self._emit(type="node.phase", path=base_path, data={"phase": "REPORTING"}))
                out.append(self._emit(type="node.phase", path=base_path, data={"phase": "DONE"}))
                out.append(self._emit(type="node.finished", path=base_path, data=data))
                return out

            if ev.type == "run_waiting_human":
                data: Dict[str, Any] = {"status": "pending"}
                error_kind = ev.payload.get("error_kind")
                if isinstance(error_kind, str) and error_kind.strip():
                    data["error_kind"] = error_kind.strip()
                out.append(self._emit(type="node.phase", path=base_path, data={"phase": "REPORTING"}))
                out.append(self._emit(type="node.phase", path=base_path, data={"phase": "DONE"}))
                out.append(self._emit(type="node.finished", path=base_path, data=data))
                return out

            # run_cancelled：在本仓多数语义用于“中断等待”（例如审批挂起），UI 层用 pending 表达更稳妥。
            status = "pending"
            out.append(self._emit(type="node.phase", path=base_path, data={"phase": "REPORTING"}))
            out.append(self._emit(type="node.phase", path=base_path, data={"phase": "DONE"}))
            out.append(self._emit(type="node.finished", path=base_path, data={"status": status}))
            return out

        if ev.type == "tool_call_requested":
            call_id = str(ev.payload.get("call_id") or "").strip()
            tool = str(ev.payload.get("name") or "").strip()
            args_summary = _summarize_dict(ev.payload.get("args")) or _summarize_dict(ev.payload.get("arguments"))
            path = list(base_path)
            if tool in {"skill_exec", "skill_ref_read"}:
                args = ev.payload.get("args") if isinstance(ev.payload.get("args"), dict) else None
                if args is None:
                    args = ev.payload.get("arguments") if isinstance(ev.payload.get("arguments"), dict) else None

                locator = None
                if isinstance(ev.payload.get("skill_locator"), str) and str(ev.payload.get("skill_locator")).strip():
                    locator = str(ev.payload.get("skill_locator")).strip()
                if locator is None and isinstance(args, dict):
                    if isinstance(args.get("skill_locator"), str) and str(args.get("skill_locator")).strip():
                        locator = str(args.get("skill_locator")).strip()
                if locator is None and isinstance(args, dict):
                    mention = args.get("mention_text") or args.get("skill_mention")
                    if isinstance(mention, str) and mention.strip():
                        locator = self._skill_mention_to_locator.get(mention.strip())
                if locator is None and isinstance(args, dict):
                    sn = args.get("skill_name")
                    if isinstance(sn, str) and sn.strip():
                        locator = self._skill_name_to_locator.get(sn.strip())
                if isinstance(locator, str) and locator.strip():
                    path.append(PathSegment(kind="skill", id=locator.strip()))
            if tool:
                path.append(PathSegment(kind="tool", id=tool))
            if call_id:
                path.append(PathSegment(kind="call", id=call_id))
                # 绑定 call origin：后续 finished/approval 必须复用该归属（哪来哪去）
                self._call_origin_path.setdefault(call_id, list(path))
                # 记录 step_id -> call_id（approvals 事件可能缺 call_id）
                step_scope_key = self._step_scope_key(ctx=ctx)
                if step_scope_key:
                    self._step_scope_to_call_id[step_scope_key] = call_id
                    if tool:
                        self._step_scope_tool_to_call_id[(step_scope_key, tool)] = call_id
            out.append(self._emit(type="node.phase", path=base_path, data={"phase": "TOOL_RUNNING"}))
            data = {"tool": tool, "call_id": call_id}
            if args_summary is not None:
                data["args_summary"] = args_summary
            out.append(self._emit(type="tool.requested", path=path, data=data, evidence=Evidence(call_id=call_id)))
            return out

        if ev.type == "approval_requested":
            tool = str(ev.payload.get("tool") or "").strip()
            call_id = str(ev.payload.get("call_id") or "").strip()
            approval_key = ev.payload.get("approval_key")
            unresolved = False
            if not call_id:
                recovered = self._best_effort_call_id_from_step(ctx=ctx, tool=tool)
                if recovered:
                    call_id = recovered
                else:
                    unresolved = True

            origin = self._call_origin_path.get(call_id) if call_id else None
            path = list(origin) if origin is not None else list(base_path)
            if origin is None:
                if tool:
                    path.append(PathSegment(kind="tool", id=tool))
                if call_id:
                    path.append(PathSegment(kind="call", id=call_id))
                    # best-effort：即便 tool.requested 缺失，也先绑定 origin，避免后续归属漂移
                    self._call_origin_path.setdefault(call_id, list(path))
            path.append(PathSegment(kind="approval", id=str(approval_key or call_id or "approval")))
            out.append(self._emit(type="node.phase", path=base_path, data={"phase": "WAITING_APPROVAL"}))
            data = {"tool": tool}
            if call_id:
                data["call_id"] = call_id
            if approval_key is not None:
                data["approval_key"] = str(approval_key)
            if unresolved:
                # 按 D4 的最小可诊断信号：fail-open，但不得静默
                data["correlation"] = "missing_call_id"
                data["correlation_error"] = {
                    "kind": "missing_call_id",
                    "strategy": "step_id",
                    "step_id": str(ctx.step_id or ""),
                    "tool": tool,
                }
            out.append(
                self._emit(
                    type="approval.requested",
                    path=path,
                    data=data,
                    evidence=Evidence(call_id=call_id) if call_id else None,
                )
            )
            return out

        if ev.type == "approval_decided":
            tool = str(ev.payload.get("tool") or "").strip()
            call_id = str(ev.payload.get("call_id") or "").strip()
            decision = str(ev.payload.get("decision") or "").strip()
            reason = ev.payload.get("reason")
            approval_key = ev.payload.get("approval_key")
            unresolved = False
            if not call_id:
                recovered = self._best_effort_call_id_from_step(ctx=ctx, tool=tool)
                if recovered:
                    call_id = recovered
                else:
                    unresolved = True

            origin = self._call_origin_path.get(call_id) if call_id else None
            path = list(origin) if origin is not None else list(base_path)
            if origin is None:
                if tool:
                    path.append(PathSegment(kind="tool", id=tool))
                if call_id:
                    path.append(PathSegment(kind="call", id=call_id))
                    # best-effort：即便 tool.requested 缺失，也先绑定 origin，避免后续归属漂移
                    self._call_origin_path.setdefault(call_id, list(path))
            path.append(PathSegment(kind="approval", id=str(approval_key or call_id or "approval")))
            out.append(self._emit(type="node.phase", path=base_path, data={"phase": "TOOL_RUNNING"}))
            data = {"tool": tool, "decision": decision or "unknown"}
            if call_id:
                data["call_id"] = call_id
            if reason is not None:
                data["reason"] = str(reason)
            if unresolved:
                data["correlation"] = "missing_call_id"
                data["correlation_error"] = {
                    "kind": "missing_call_id",
                    "strategy": "step_id",
                    "step_id": str(ctx.step_id or ""),
                    "tool": tool,
                }
            out.append(
                self._emit(
                    type="approval.decided",
                    path=path,
                    data=data,
                    evidence=Evidence(call_id=call_id) if call_id else None,
                )
            )
            return out

        if ev.type == "tool_call_finished":
            call_id = str(ev.payload.get("call_id") or "").strip()
            tool = str(ev.payload.get("tool") or "").strip()
            result = ev.payload.get("result") if isinstance(ev.payload.get("result"), dict) else {}
            ok = result.get("ok") if isinstance(result.get("ok"), bool) else None
            error_kind = result.get("error_kind") if isinstance(result.get("error_kind"), str) else None
            result_summary = _summarize_dict(result.get("data"))
            origin = self._call_origin_path.get(call_id) if call_id else None
            path = list(origin) if origin is not None else list(base_path)
            if origin is None:
                if tool:
                    path.append(PathSegment(kind="tool", id=tool))
                if call_id:
                    path.append(PathSegment(kind="call", id=call_id))
            out.append(self._emit(type="node.phase", path=base_path, data={"phase": "THINKING"}))
            data = {"tool": tool, "call_id": call_id, "ok": bool(ok)}
            if error_kind:
                data["error_kind"] = error_kind
            if result_summary is not None:
                data["result_summary"] = result_summary
            out.append(self._emit(type="tool.finished", path=path, data=data, evidence=Evidence(call_id=call_id)))
            return out

        return []

    def on_terminal(self, result: CapabilityResult) -> List[RuntimeEvent]:
        terminal_status = _normalize_terminal_status(result.status)
        evidence = self._evidence_from_node_report(result.node_report)
        data: Dict[str, Any] = {"status": terminal_status}
        if result.node_report is not None:
            structured_output = result.node_report.meta.get("structured_output")
            if isinstance(structured_output, dict):
                data["structured_output"] = dict(structured_output)
            output_validation = result.node_report.meta.get("output_validation")
            if isinstance(output_validation, dict):
                data["output_validation"] = dict(output_validation)
        host_runtime = project_host_runtime_data(result)
        if isinstance(host_runtime, dict):
            data["host_runtime"] = host_runtime
        return [
            self._emit(
                type="run.status",
                path=self._base_path(),
                data=data,
                evidence=evidence,
            )
        ]

    def _evidence_from_node_report(self, report: Optional[NodeReport]) -> Optional[Evidence]:
        if report is None:
            return None
        ev = Evidence(node_report_schema=getattr(report, "schema_id", None))
        if isinstance(report.events_path, str) and report.events_path:
            ev.events_path = report.events_path
        if report.artifacts and isinstance(report.artifacts[0], str) and report.artifacts[0].strip():
            ev.artifact_path = report.artifacts[0].strip()
        return ev
