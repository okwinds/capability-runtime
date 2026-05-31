from __future__ import annotations

"""Dynamic DAG preview compiler and execution helpers."""

import hashlib
import json
from collections import deque
from dataclasses import asdict, replace
from typing import Any, Iterable, Mapping, Sequence

from .protocol.dynamic_workflow import DynamicWorkflowNode, DynamicWorkflowPlan


_ALLOWED_KINDS = {"agent", "workflow", "tool", "model", "action", "skill", "custom"}
_DEFAULT_MAX_DYNAMIC_NODES = 64


class DynamicWorkflowPlanError(ValueError):
    """Stable Dynamic DAG contract error."""

    def __init__(self, error_code: str, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = str(error_code)
        self.details = dict(details or {})


def compile_task_dag(
    value: Mapping[str, Any] | Any,
    *,
    registry_ids: Iterable[str] | None = None,
    max_nodes: int = _DEFAULT_MAX_DYNAMIC_NODES,
) -> DynamicWorkflowPlan:
    """Compile a TaskDAG-like shape into this repo's neutral plan."""

    raw = _object_to_mapping(value)
    graph_id = _non_empty_string(raw.get("graph_id")) or "dynamic-dag"
    tasks = _get_tasks(raw)
    if len(tasks) > int(max_nodes):
        raise DynamicWorkflowPlanError(
            "DYNAMIC_DAG_TOO_LARGE",
            f"Dynamic DAG has {len(tasks)} nodes, limit is {int(max_nodes)}",
            details={"graph_id": graph_id, "node_count": len(tasks), "max_nodes": int(max_nodes)},
        )

    registry_set = {str(item) for item in registry_ids} if registry_ids is not None else None
    nodes: list[DynamicWorkflowNode] = []
    diagnostics: list[dict[str, Any]] = []
    seen: set[str] = set()

    for key in ("task_schema_version", "semantic_outputs", "policies"):
        if key in raw:
            diagnostics.append({key: _safe_summary(raw.get(key))})
    if isinstance(raw.get("diagnostics"), Sequence) and not isinstance(raw.get("diagnostics"), (str, bytes, bytearray)):
        for item in list(raw.get("diagnostics") or [])[:8]:
            diagnostics.append(_safe_summary(item) if isinstance(_safe_summary(item), dict) else {"diagnostic": _safe_summary(item)})

    for item in tasks:
        task = _object_to_mapping(item)
        node_id = _non_empty_string(task.get("id"))
        if node_id is None:
            raise DynamicWorkflowPlanError("DYNAMIC_DAG_INVALID", "Dynamic DAG node id is required", details={"graph_id": graph_id})
        if node_id in seen:
            raise DynamicWorkflowPlanError(
                "DYNAMIC_DAG_DUPLICATE_NODE",
                f"Duplicate Dynamic DAG node id: {node_id}",
                details={"graph_id": graph_id, "node_id": node_id},
            )
        seen.add(node_id)

        kind = _non_empty_string(task.get("kind")) or "custom"
        if kind not in _ALLOWED_KINDS:
            raise DynamicWorkflowPlanError(
                "DYNAMIC_DAG_INVALID",
                f"Unsupported Dynamic DAG node kind: {kind}",
                details={"graph_id": graph_id, "node_id": node_id, "kind": kind},
            )

        inputs = _normalize_inputs(task.get("inputs"))
        capability_id = _resolve_capability_id(task=task, inputs=inputs, registry_ids=registry_set)

        node = DynamicWorkflowNode(
            id=node_id,
            kind=kind,  # type: ignore[arg-type]
            title=_non_empty_string(task.get("title")),
            purpose=_non_empty_string(task.get("purpose")),
            depends_on=_normalize_string_tuple(task.get("depends_on"), field_name="depends_on", graph_id=graph_id, node_id=node_id),
            capability_id=capability_id,
            inputs=inputs,
            produces=_normalize_produces(task.get("produces")),
            approval_required=bool(task.get("approval")),
        )
        nodes.append(node)

        node_diag: dict[str, Any] = {"node_id": node_id}
        for key in ("side_effect_policy", "fallback"):
            if key in task:
                node_diag[key] = _safe_summary(task.get(key))
        if len(node_diag) > 1:
            diagnostics.append(node_diag)

    plan_without_hash = DynamicWorkflowPlan(
        graph_id=graph_id,
        nodes=tuple(nodes),
        source="task_dag",
        plan_hash="",
        diagnostics=tuple(diagnostics),
    )
    validate_dynamic_workflow_plan(plan_without_hash, max_nodes=max_nodes)
    if registry_set is not None:
        for node in plan_without_hash.nodes:
            if node.capability_id is None:
                raise DynamicWorkflowPlanError(
                    "DYNAMIC_DAG_NODE_UNRESOLVED",
                    f"Dynamic DAG node cannot resolve a registered capability: {node.id}",
                    details={"graph_id": graph_id, "node_id": node.id},
                )
    return replace(plan_without_hash, plan_hash=hash_dynamic_plan(plan_without_hash))


def validate_dynamic_workflow_plan(plan: DynamicWorkflowPlan, *, max_nodes: int = _DEFAULT_MAX_DYNAMIC_NODES) -> None:
    if not isinstance(plan, DynamicWorkflowPlan):
        raise DynamicWorkflowPlanError("DYNAMIC_DAG_INVALID", "Expected DynamicWorkflowPlan")
    if not str(plan.graph_id or "").strip():
        raise DynamicWorkflowPlanError("DYNAMIC_DAG_INVALID", "DynamicWorkflowPlan.graph_id is required")
    if len(plan.nodes) > int(max_nodes):
        raise DynamicWorkflowPlanError(
            "DYNAMIC_DAG_TOO_LARGE",
            f"Dynamic DAG has {len(plan.nodes)} nodes, limit is {int(max_nodes)}",
            details={"graph_id": plan.graph_id, "node_count": len(plan.nodes), "max_nodes": int(max_nodes)},
        )

    ids: set[str] = set()
    for node in plan.nodes:
        if not str(node.id or "").strip():
            raise DynamicWorkflowPlanError("DYNAMIC_DAG_INVALID", "DynamicWorkflowNode.id is required", details={"graph_id": plan.graph_id})
        if node.id in ids:
            raise DynamicWorkflowPlanError(
                "DYNAMIC_DAG_DUPLICATE_NODE",
                f"Duplicate Dynamic DAG node id: {node.id}",
                details={"graph_id": plan.graph_id, "node_id": node.id},
            )
        ids.add(node.id)
        if node.kind not in _ALLOWED_KINDS:
            raise DynamicWorkflowPlanError(
                "DYNAMIC_DAG_INVALID",
                f"Unsupported Dynamic DAG node kind: {node.kind}",
                details={"graph_id": plan.graph_id, "node_id": node.id, "kind": node.kind},
            )
        for dep in node.depends_on:
            if dep == node.id:
                raise DynamicWorkflowPlanError(
                    "DYNAMIC_DAG_CYCLE",
                    f"Dynamic DAG node depends on itself: {node.id}",
                    details={"graph_id": plan.graph_id, "node_id": node.id},
                )
    for node in plan.nodes:
        for dep in node.depends_on:
            if dep not in ids:
                raise DynamicWorkflowPlanError(
                    "DYNAMIC_DAG_UNKNOWN_DEPENDENCY",
                    f"Unknown Dynamic DAG dependency: {dep}",
                    details={"graph_id": plan.graph_id, "node_id": node.id, "dependency": dep},
                )
    topological_dynamic_groups(plan)


def topological_dynamic_groups(plan: DynamicWorkflowPlan) -> tuple[tuple[DynamicWorkflowNode, ...], ...]:
    nodes_by_id = {node.id: node for node in plan.nodes}
    indegree = {node.id: 0 for node in plan.nodes}
    dependents: dict[str, list[str]] = {node.id: [] for node in plan.nodes}
    for node in plan.nodes:
        for dep in node.depends_on:
            if dep not in nodes_by_id:
                raise DynamicWorkflowPlanError(
                    "DYNAMIC_DAG_UNKNOWN_DEPENDENCY",
                    f"Unknown Dynamic DAG dependency: {dep}",
                    details={"graph_id": plan.graph_id, "node_id": node.id, "dependency": dep},
                )
            indegree[node.id] += 1
            dependents[dep].append(node.id)

    queue = deque([node.id for node in plan.nodes if indegree[node.id] == 0])
    groups: list[tuple[DynamicWorkflowNode, ...]] = []
    visited = 0
    while queue:
        level_ids = list(queue)
        queue.clear()
        groups.append(tuple(nodes_by_id[node_id] for node_id in level_ids))
        for node_id in level_ids:
            visited += 1
            for dependent_id in dependents[node_id]:
                indegree[dependent_id] -= 1
                if indegree[dependent_id] == 0:
                    queue.append(dependent_id)
    if visited != len(plan.nodes):
        raise DynamicWorkflowPlanError(
            "DYNAMIC_DAG_CYCLE",
            "Dynamic DAG contains a cycle",
            details={"graph_id": plan.graph_id},
        )
    return tuple(groups)


def hash_dynamic_plan(plan: DynamicWorkflowPlan) -> str:
    payload = {
        "graph_id": plan.graph_id,
        "source": plan.source,
        "nodes": [
            {
                "id": node.id,
                "kind": node.kind,
                "title": node.title,
                "purpose": node.purpose,
                "depends_on": list(node.depends_on),
                "capability_id": node.capability_id,
                "inputs": node.inputs,
                "produces": list(node.produces),
                "approval_required": node.approval_required,
            }
            for node in plan.nodes
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _get_tasks(raw: Mapping[str, Any]) -> list[Any]:
    tasks = raw.get("tasks")
    if tasks is None:
        raise DynamicWorkflowPlanError("DYNAMIC_DAG_INVALID", "Agently TaskDAG.tasks is required")
    if not isinstance(tasks, Sequence) or isinstance(tasks, (str, bytes, bytearray)):
        raise DynamicWorkflowPlanError("DYNAMIC_DAG_INVALID", "Agently TaskDAG.tasks must be a sequence")
    return list(tasks)


def _object_to_mapping(value: Mapping[str, Any] | Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    data: dict[str, Any] = {}
    for key in (
        "graph_id",
        "task_schema_version",
        "tasks",
        "semantic_outputs",
        "policies",
        "diagnostics",
        "id",
        "kind",
        "title",
        "purpose",
        "depends_on",
        "inputs",
        "binding",
        "produces",
        "approval",
        "side_effect_policy",
        "fallback",
    ):
        if hasattr(value, key):
            data[key] = getattr(value, key)
    if data:
        return data
    raise DynamicWorkflowPlanError("DYNAMIC_DAG_INVALID", f"Unsupported TaskDAG value: {type(value).__name__}")


def _non_empty_string(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _normalize_inputs(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if value is None:
        return {}
    return {"value": value}


def _normalize_string_tuple(value: Any, *, field_name: str, graph_id: str, node_id: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        item = value.strip()
        return (item,) if item else ()
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        out: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                out.append(text)
        return tuple(out)
    raise DynamicWorkflowPlanError(
        "DYNAMIC_DAG_INVALID",
        f"Dynamic DAG node {field_name} must be a string or sequence",
        details={"graph_id": graph_id, "node_id": node_id, "field": field_name},
    )


def _normalize_produces(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, Mapping):
        return tuple(str(key).strip() for key in value.keys() if str(key).strip())
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return (str(value),)


def _resolve_capability_id(
    *,
    task: Mapping[str, Any],
    inputs: Mapping[str, Any],
    registry_ids: set[str] | None,
) -> str | None:
    candidates: list[str] = []
    binding = _non_empty_string(task.get("binding"))
    if binding is not None:
        candidates.append(binding)
    input_capability = _non_empty_string(inputs.get("capability_id"))
    if input_capability is not None:
        candidates.append(input_capability)
    if registry_ids is None:
        return candidates[0] if candidates else None
    for candidate in candidates:
        if candidate in registry_ids:
            return candidate
    return None


def _safe_summary(value: Any, *, depth: int = 0) -> Any:
    if depth >= 3:
        return "<omitted>"
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 12:
                out["omitted_count"] = len(value) - 12
                break
            out[str(key)] = _safe_summary(item, depth=depth + 1)
        return out
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = list(value)
        return [_safe_summary(item, depth=depth + 1) for item in items[:12]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > 240:
            return value[:240] + "...<truncated>"
        return value
    try:
        return asdict(value)
    except Exception:
        return str(value)


__all__ = [
    "DynamicWorkflowPlanError",
    "compile_task_dag",
    "validate_dynamic_workflow_plan",
    "topological_dynamic_groups",
    "hash_dynamic_plan",
]
