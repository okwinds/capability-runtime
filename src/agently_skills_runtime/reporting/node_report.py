"""
NodeReportBuilder：把 SDK `AgentEvent` 聚合为 NodeReport v2。

对齐规格：
- `openspec/specs/evidence-chain/spec.md`
"""

from __future__ import annotations

import importlib.metadata
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from agent_sdk.core.contracts import AgentEvent

from ..types import NodeReportV2, NodeToolCallReport


def _get_agent_sdk_version() -> Optional[str]:
    """读取 agent_sdk.__version__（若可用）。"""

    try:
        import agent_sdk  # type: ignore

        v = getattr(agent_sdk, "__version__", None)
        if isinstance(v, str) and v.strip():
            return v.strip()
    except Exception:
        return None
    return None


def _get_dist_version(dist_name: str) -> Optional[str]:
    """读取已安装 distribution 的版本号；不存在则返回 None。"""

    try:
        return importlib.metadata.version(dist_name)
    except Exception:
        return None


def _get_first_dist_version(dist_names: List[str]) -> Optional[str]:
    """
    读取一组候选 distribution 名称中的第一个可用版本号。

    参数：
    - dist_names：候选 dist 名称列表（按优先级排序）

    返回：
    - 第一个可读取的版本号；都不可用则返回 None
    """

    for name in dist_names:
        v = _get_dist_version(name)
        if v:
            return v
    return None


@dataclass
class NodeReportBuilder:
    """
    NodeReport 聚合器。

    约束：
    - 以证据链为主（tool/approval/run_* 事件）
    - 不推断 domain payload
    - 不把 stdout/stderr 大段塞进 NodeReport（避免泄露与膨胀）
    """

    def build(self, *, events: List[AgentEvent]) -> NodeReportV2:
        """
        从一次 run 的事件序列构造 NodeReport v2。

        参数：
        - `events`：按发生顺序排列的 SDK AgentEvent 列表

        返回：
        - NodeReportV2
        """

        if not events:
            raise ValueError("events must be non-empty")

        run_id = events[0].run_id
        turn_id = None
        for ev in events:
            if ev.turn_id:
                turn_id = ev.turn_id

        activated_skills: List[str] = []
        seen_skills: set[str] = set()

        artifacts: List[str] = []
        seen_artifacts: set[str] = set()

        def _add_artifact(path: str) -> None:
            """
            记录 artifact 路径（去重但保持首次出现顺序）。

            参数：
            - path：artifact 路径字符串（必须为非空）
            """

            p = str(path or "").strip()
            if not p or p in seen_artifacts:
                return
            artifacts.append(p)
            seen_artifacts.add(p)

        # call_id -> aggregated fields
        tool_calls: Dict[str, Dict[str, Any]] = {}
        approval_pending: set[str] = set()
        requires_approval_inferred: set[str] = set()

        # 兼容 SDK 默认 approvals 事件形态：
        # - tool_call_requested payload 带 call_id/name
        # - approval_requested/approval_decided payload 可能不带 call_id，仅能通过 step_id 关联到同一步的 tool_call_requested
        step_to_call: Dict[str, Dict[str, str]] = {}

        completion_status: Optional[str] = None
        completion_reason = ""
        events_path: Optional[str] = None
        final_error_kind: Optional[str] = None
        final_message: Optional[str] = None

        def _ensure_tool(call_id: str, *, name: str) -> Dict[str, Any]:
            """获取/初始化工具调用聚合槽位（以 call_id 为主键）。"""

            if call_id not in tool_calls:
                tool_calls[call_id] = {
                    "call_id": call_id,
                    "name": name,
                    "requires_approval": False,
                    "approval_key": None,
                    "approval_decision": None,
                    "approval_reason": None,
                    "ok": False,
                    "error_kind": None,
                    "data": None,
                }
            return tool_calls[call_id]

        for ev in events:
            artifact_path = ev.payload.get("artifact_path")
            if isinstance(artifact_path, str) and artifact_path.strip():
                _add_artifact(artifact_path)

            if ev.type == "skill_injected":
                skill_name = str(ev.payload.get("skill_name") or "").strip()
                if skill_name and skill_name not in seen_skills:
                    activated_skills.append(skill_name)
                    seen_skills.add(skill_name)

            if ev.type == "tool_call_requested":
                call_id = str(ev.payload.get("call_id") or "").strip()
                name = str(ev.payload.get("name") or "").strip()
                if call_id and name:
                    _ensure_tool(call_id, name=name)
                    if ev.step_id:
                        step_to_call[str(ev.step_id)] = {"call_id": call_id, "tool": name}

            if ev.type == "approval_requested":
                tool = str(ev.payload.get("tool") or "").strip()
                approval_key = ev.payload.get("approval_key")
                call_id = str(ev.payload.get("call_id") or "").strip()
                if not call_id and ev.step_id:
                    mapped = step_to_call.get(str(ev.step_id))
                    if mapped and (not tool or tool == mapped.get("tool")):
                        call_id = mapped.get("call_id", "")
                        tool = tool or mapped.get("tool", "")
                if call_id and tool:
                    t = _ensure_tool(call_id, name=tool)
                    t["requires_approval"] = True
                    # Bridge 无法稳定读取 tool spec 时，只能通过 approval_* 事件推断 requires_approval。
                    requires_approval_inferred.add(call_id)
                    if isinstance(approval_key, str) and approval_key:
                        t["approval_key"] = approval_key
                    approval_pending.add(call_id)

            if ev.type == "approval_decided":
                tool = str(ev.payload.get("tool") or "").strip()
                decision = ev.payload.get("decision")
                reason = ev.payload.get("reason")
                call_id = str(ev.payload.get("call_id") or "").strip()
                if not call_id and ev.step_id:
                    mapped = step_to_call.get(str(ev.step_id))
                    if mapped and (not tool or tool == mapped.get("tool")):
                        call_id = mapped.get("call_id", "")
                        tool = tool or mapped.get("tool", "")
                if call_id and tool:
                    t = _ensure_tool(call_id, name=tool)
                    t["requires_approval"] = True
                    requires_approval_inferred.add(call_id)
                    if isinstance(decision, str) and decision:
                        t["approval_decision"] = decision
                    if isinstance(reason, str) and reason:
                        t["approval_reason"] = reason
                    approval_pending.discard(call_id)

            if ev.type == "tool_call_finished":
                call_id = str(ev.payload.get("call_id") or "").strip()
                tool = str(ev.payload.get("tool") or "").strip()
                result = ev.payload.get("result") or {}
                if call_id and tool:
                    t = _ensure_tool(call_id, name=tool)
                    if isinstance(result, dict):
                        ok = result.get("ok")
                        if isinstance(ok, bool):
                            t["ok"] = ok
                        error_kind = result.get("error_kind")
                        if isinstance(error_kind, str) and error_kind:
                            t["error_kind"] = error_kind
                        data = result.get("data")
                        if isinstance(data, dict):
                            t["data"] = data

            if ev.type in ("run_completed", "run_failed", "run_cancelled"):
                # skills-runtime-sdk>=1.0 使用 `wal_locator` 作为 WAL/事件证据链定位符；
                # 本仓对外仍沿用 `events_path` 字段名，语义上存放 locator 字符串（可能是文件路径，也可能是 wal://...）。
                locator_raw = ev.payload.get("events_path")
                if not (isinstance(locator_raw, str) and locator_raw.strip()):
                    locator_raw = ev.payload.get("wal_locator")
                if isinstance(locator_raw, str) and locator_raw.strip():
                    events_path = locator_raw.strip()

                # artifacts（run 级别产物列表）
                artifacts_raw = ev.payload.get("artifacts")
                if isinstance(artifacts_raw, list):
                    for item in artifacts_raw:
                        if isinstance(item, str) and item.strip():
                            _add_artifact(item)

                completion_reason = ev.type
                if ev.type == "run_completed":
                    completion_status = "success"
                elif ev.type == "run_failed":
                    final_error_kind = ev.payload.get("error_kind") if isinstance(ev.payload.get("error_kind"), str) else None
                    final_message = ev.payload.get("message") if isinstance(ev.payload.get("message"), str) else None
                    # 对齐契约：预算耗尽属于“未完成”而非“失败”（Host 可能需要走补偿/降级）。
                    if final_error_kind in ("budget_exceeded", "terminated"):
                        completion_status = "incomplete"
                    else:
                        completion_status = "failed"
                else:
                    completion_status = "incomplete"
                    final_message = ev.payload.get("message") if isinstance(ev.payload.get("message"), str) else None

        # 优先级：needs_approval > run_failed > run_cancelled > run_completed
        status = completion_status or "incomplete"
        reason = None
        if approval_pending:
            status = "needs_approval"
            reason = "approval_pending"
        elif status == "failed":
            # 失败原因粗分类：优先 error_kind，其次 message
            if final_error_kind:
                if final_error_kind in ("permission", "policy", "approval_denied"):
                    reason = "tool_error"
                elif final_error_kind in (
                    "validation",
                    "not_found",
                    "config_error",
                    "skill_config_error",
                    "missing_env_var",
                    "SKILL_PREFLIGHT_FAILED",
                ):
                    reason = "skill_config_error"
                elif final_error_kind.startswith("network_") or final_error_kind in (
                    "auth_error",
                    "rate_limited",
                    "server_error",
                    "http_error",
                    "context_length_exceeded",
                ):
                    reason = "llm_error"
                else:
                    reason = "unknown"
            else:
                reason = "unknown"
        elif status == "incomplete":
            if final_error_kind == "budget_exceeded":
                reason = "budget_exceeded"
            elif final_error_kind == "terminated":
                reason = "cancelled"
            else:
                reason = "cancelled" if completion_reason == "run_cancelled" else "unknown"

        tool_reports = [
            NodeToolCallReport.model_validate(item) for item in tool_calls.values() if isinstance(item, dict)
        ]

        report = NodeReportV2(
            status=status,  # type: ignore[arg-type]
            reason=reason,
            completion_reason=completion_reason or "",
            engine={
                "name": "skills-runtime-sdk-python",
                "module": "agent_sdk",
                "version": _get_agent_sdk_version()
                or _get_first_dist_version(["skills-runtime-sdk", "skills-runtime-sdk-python"]),
            },
            bridge={"name": "agently-skills-runtime", "version": _get_first_dist_version(["agently-skills-runtime"])},
            run_id=run_id,
            turn_id=turn_id,
            events_path=events_path,
            activated_skills=activated_skills,
            tool_calls=tool_reports,
            artifacts=artifacts,
            meta={
                "missing_events_path": events_path is None,
                "final_message": final_message,
                **(
                    {
                        "approval_inference": {
                            "requires_approval_call_ids": sorted(requires_approval_inferred),
                            "source": "events_only",
                        }
                    }
                    if requires_approval_inferred
                    else {}
                ),
            },
        )
        return report


def build_node_report_from_events(events: Iterable[AgentEvent]) -> NodeReportV2:
    """便捷函数：从事件迭代器构造 NodeReport v2。"""

    builder = NodeReportBuilder()
    return builder.build(events=list(events))
