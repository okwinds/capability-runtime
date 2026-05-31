from __future__ import annotations

"""Dynamic workflow preview protocol types.

This module is intentionally upstream-neutral. It must not import Agently or
skills-runtime runtime objects; adapters compile external shapes into these
dataclasses first.
"""

from dataclasses import dataclass, field
from typing import Any, Literal


DynamicWorkflowNodeKind = Literal["agent", "workflow", "tool", "model", "action", "skill", "custom"]
DynamicWorkflowPlanSource = Literal["task_dag", "host", "model"]


@dataclass(frozen=True)
class DynamicWorkflowNode:
    id: str
    kind: DynamicWorkflowNodeKind
    title: str | None = None
    purpose: str | None = None
    depends_on: tuple[str, ...] = ()
    capability_id: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    produces: tuple[str, ...] = ()
    approval_required: bool = False


@dataclass(frozen=True)
class DynamicWorkflowPlan:
    graph_id: str
    nodes: tuple[DynamicWorkflowNode, ...]
    source: DynamicWorkflowPlanSource
    plan_hash: str
    diagnostics: tuple[dict[str, Any], ...] = ()
