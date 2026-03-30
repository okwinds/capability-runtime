from __future__ import annotations

"""Runtime canonical capability manifest / descriptor helpers."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .protocol.agent import AgentSpec
from .protocol.capability import CapabilityKind, CapabilityRef, CapabilitySpec
from .protocol.workflow import ConditionalStep, LoopStep, ParallelStep, Step, WorkflowSpec, WorkflowStep


class CapabilityVisibility(str, Enum):
    """能力可见性。"""

    PUBLIC = "public"
    INTERNAL = "internal"


@dataclass(frozen=True)
class CapabilityManifestEntry:
    """
    manifest entry：描述一个 capability 的宿主可消费元数据。

    参数：
    - capability_id：能力唯一 ID，必须与 spec.base.id 对齐
    - kind：能力类型
    - version：能力版本
    - name/description：宿主展示用摘要
    - tags：能力标签
    - visibility：可见性（public/internal）
    - expose：是否默认出现在对外发现列表
    - source：注册来源
    - metadata：扩展字段
    """

    capability_id: str
    kind: CapabilityKind
    version: str
    name: str | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    visibility: CapabilityVisibility = CapabilityVisibility.PUBLIC
    expose: bool = True
    source: str = "runtime.register"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CapabilityDescriptor:
    """
    descriptor：manifest entry + spec + 依赖的统一描述结构。

    参数：
    - entry：manifest 元数据
    - spec：原始 AgentSpec / WorkflowSpec；仅注册 manifest entry 时允许为空
    - dependencies：收敛后的 capability refs
    """

    entry: CapabilityManifestEntry
    spec: AgentSpec | WorkflowSpec | None = None
    dependencies: list[CapabilityRef] = field(default_factory=list)


def build_manifest_entry_from_spec(
    spec: AgentSpec | WorkflowSpec,
    *,
    source: str = "runtime.register",
) -> CapabilityManifestEntry:
    """
    基于 spec.base 构造默认 manifest entry。

    参数：
    - spec：AgentSpec 或 WorkflowSpec
    - source：注册来源

    返回：
    - 衍生出的默认 CapabilityManifestEntry
    """

    base = spec.base
    return CapabilityManifestEntry(
        capability_id=base.id,
        kind=base.kind,
        version=base.version,
        name=base.name,
        description=base.description,
        tags=list(base.tags),
        source=source,
        metadata=dict(base.metadata),
    )


def collect_capability_dependencies(spec: AgentSpec | WorkflowSpec | None) -> list[CapabilityRef]:
    """
    从 spec 收敛 capability 依赖引用。

    参数：
    - spec：AgentSpec 或 WorkflowSpec；为空时返回空列表

    返回：
    - 去重且保持首次出现顺序的 CapabilityRef 列表
    """

    if spec is None:
        return []

    collected: list[CapabilityRef] = []
    seen: set[tuple[str, CapabilityKind | None]] = set()

    def add_ref(ref: CapabilityRef) -> None:
        key = (ref.id, ref.kind)
        if key in seen:
            return
        seen.add(key)
        collected.append(ref)

    if isinstance(spec, AgentSpec):
        for ref in spec.collaborators:
            add_ref(ref)
        for ref in spec.callable_workflows:
            add_ref(ref)
        return collected

    def walk_workflow_step(step: WorkflowStep) -> None:
        if isinstance(step, (Step, LoopStep)):
            add_ref(step.capability)
            return
        if isinstance(step, ParallelStep):
            for branch in step.branches:
                walk_workflow_step(branch)
            return
        if isinstance(step, ConditionalStep):
            for branch in step.branches.values():
                walk_workflow_step(branch)
            if step.default is not None:
                walk_workflow_step(step.default)

    for workflow_step in spec.steps:
        walk_workflow_step(workflow_step)
    return collected


def validate_manifest_entry_matches_spec(entry: CapabilityManifestEntry, spec: AgentSpec | WorkflowSpec) -> None:
    """
    校验显式 manifest entry 与 spec.base 的关键字段一致。

    参数：
    - entry：宿主声明的 manifest entry
    - spec：要注册的能力声明

    异常：
    - ValueError：entry 与 spec.base 不一致
    """

    base: CapabilitySpec = spec.base
    if entry.capability_id != base.id:
        raise ValueError(
            f"Manifest entry capability_id mismatch: {entry.capability_id!r} != {base.id!r}"
        )
    if entry.kind != base.kind:
        raise ValueError(f"Manifest entry kind mismatch: {entry.kind!r} != {base.kind!r}")


__all__ = [
    "CapabilityVisibility",
    "CapabilityManifestEntry",
    "CapabilityDescriptor",
    "build_manifest_entry_from_spec",
    "collect_capability_dependencies",
    "validate_manifest_entry_matches_spec",
]
