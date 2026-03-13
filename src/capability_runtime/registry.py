"""能力注册表——所有 Spec 的中央存储和查询。"""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Union

from .manifest import (
    CapabilityDescriptor,
    CapabilityManifestEntry,
    CapabilityVisibility,
    build_manifest_entry_from_spec,
    collect_capability_dependencies,
    validate_manifest_entry_matches_spec,
)
from .protocol.agent import AgentSpec
from .protocol.capability import CapabilityKind, CapabilitySpec
from .protocol.workflow import ConditionalStep, LoopStep, ParallelStep, Step, WorkflowSpec

AnySpec = Union[AgentSpec, WorkflowSpec]


def _get_base(spec: AnySpec) -> CapabilitySpec:
    """
    从具体 Spec 中提取公共 base。

    参数：
    - spec：AgentSpec 或 WorkflowSpec

    返回：
    - CapabilitySpec（公共字段）
    """

    return spec.base


class CapabilityRegistry:
    """
    能力注册表。

    线程安全说明：当前为单线程设计（asyncio 单事件循环）。
    """

    def __init__(self) -> None:
        self._store: Dict[str, AnySpec] = {}
        self._manifest_store: Dict[str, CapabilityManifestEntry] = {}

    def register(self, spec: AnySpec) -> None:
        """
        注册一个能力。

        参数：
        - spec：能力声明（AgentSpec/WorkflowSpec）

        说明：
        - 重复注册同一 ID 会覆盖（last-write-wins）。
        """

        self.register_with_manifest(spec)

    def register_with_manifest(
        self,
        spec: AnySpec,
        *,
        entry: CapabilityManifestEntry | None = None,
    ) -> CapabilityManifestEntry:
        """
        注册能力并同步维护 manifest entry。

        参数：
        - spec：能力声明（AgentSpec/WorkflowSpec）
        - entry：可选显式 manifest entry；为空时基于 spec.base 自动生成

        返回：
        - 实际存储的 manifest entry
        """

        base = _get_base(spec)
        manifest_entry = entry or build_manifest_entry_from_spec(spec)
        validate_manifest_entry_matches_spec(manifest_entry, spec)
        self._store[base.id] = spec
        self._manifest_store[base.id] = manifest_entry
        return manifest_entry

    def register_manifest_entry(self, entry: CapabilityManifestEntry) -> CapabilityManifestEntry:
        """
        仅注册 manifest entry（允许尚未存在 spec）。

        参数：
        - entry：manifest 元数据

        返回：
        - 原样返回已存储 entry
        """

        self._manifest_store[entry.capability_id] = entry
        return entry

    def get(self, capability_id: str) -> Optional[AnySpec]:
        """
        查找能力，不存在返回 None。

        参数：
        - capability_id：能力 ID
        """

        return self._store.get(capability_id)

    def get_or_raise(self, capability_id: str) -> AnySpec:
        """
        查找能力，不存在抛 KeyError。

        参数：
        - capability_id：能力 ID
        """

        spec = self.get(capability_id)
        if spec is None:
            raise KeyError(f"Capability not found: {capability_id!r}")
        return spec

    def list_all(self) -> List[AnySpec]:
        """列出所有已注册能力。"""

        return list(self._store.values())

    def list_by_kind(self, kind: CapabilityKind) -> List[AnySpec]:
        """
        列出指定种类的所有能力。

        参数：
        - kind：能力类型
        """

        return [s for s in self._store.values() if _get_base(s).kind == kind]

    def list_ids(self) -> List[str]:
        """列出所有已注册能力的 ID。"""

        return list(self._store.keys())

    def get_manifest_entry(self, capability_id: str) -> CapabilityManifestEntry | None:
        """
        查找 manifest entry，不存在返回 None。

        参数：
        - capability_id：能力 ID
        """

        entry = self._manifest_store.get(capability_id)
        if entry is not None:
            return entry
        spec = self._store.get(capability_id)
        if spec is None:
            return None
        entry = build_manifest_entry_from_spec(spec)
        self._manifest_store[capability_id] = entry
        return entry

    def get_descriptor(self, capability_id: str) -> CapabilityDescriptor | None:
        """
        查询 capability descriptor。

        参数：
        - capability_id：能力 ID
        """

        entry = self.get_manifest_entry(capability_id)
        if entry is None:
            return None
        spec = self._store.get(capability_id)
        return CapabilityDescriptor(
            entry=entry,
            spec=spec,
            dependencies=collect_capability_dependencies(spec),
        )

    def list_descriptors(
        self,
        *,
        visibility: CapabilityVisibility | None = None,
        exposed_only: bool = False,
    ) -> list[CapabilityDescriptor]:
        """
        列出 capability descriptors。

        参数：
        - visibility：可选可见性过滤
        - exposed_only：仅返回 `entry.expose=True` 的能力
        """

        ids: list[str] = list(self._manifest_store.keys())
        for capability_id in self._store.keys():
            if capability_id not in self._manifest_store:
                ids.append(capability_id)

        descriptors: list[CapabilityDescriptor] = []
        for capability_id in ids:
            descriptor = self.get_descriptor(capability_id)
            if descriptor is None:
                continue
            if visibility is not None and descriptor.entry.visibility != visibility:
                continue
            if exposed_only and not descriptor.entry.expose:
                continue
            descriptors.append(descriptor)
        return descriptors

    def has(self, capability_id: str) -> bool:
        """
        检查能力是否已注册。

        参数：
        - capability_id：能力 ID
        """

        return capability_id in self._store

    def unregister(self, capability_id: str) -> bool:
        """
        注销能力。

        参数：
        - capability_id：能力 ID

        返回：
        - True 表示存在并已删除；False 表示不存在
        """

        if capability_id in self._store:
            del self._store[capability_id]
            removed = True
        else:
            removed = False
        if capability_id in self._manifest_store:
            del self._manifest_store[capability_id]
            return True
        return removed

    def validate_dependencies(self) -> List[str]:
        """
        校验所有能力的依赖是否已注册。

        检查范围：
        - AgentSpec.collaborators / callable_workflows 中引用的能力 ID
        - WorkflowSpec 中所有 Step/LoopStep 的 capability.id
        - ParallelStep.branches 内的步骤
        - ConditionalStep.branches/default 内的步骤

        返回：
        - 缺失的 ID 列表（空列表表示全部满足）
        """

        missing: Set[str] = set()

        for spec in self._store.values():
            if isinstance(spec, AgentSpec):
                for ref in spec.collaborators:
                    if ref.id not in self._store:
                        missing.add(ref.id)
                for ref in spec.callable_workflows:
                    if ref.id not in self._store:
                        missing.add(ref.id)

            elif isinstance(spec, WorkflowSpec):
                self._collect_step_deps(spec.steps, missing)

        return sorted(missing)

    def _collect_step_deps(self, steps: list, missing: Set[str]) -> None:
        """
        递归收集步骤中的能力依赖。

        参数：
        - steps：步骤列表（可能包含嵌套步骤）
        - missing：缺失依赖的能力 ID（原地写入）
        """

        for step in steps:
            if isinstance(step, (Step, LoopStep)):
                if step.capability.id not in self._store:
                    missing.add(step.capability.id)
            elif isinstance(step, ParallelStep):
                # WorkflowAdapter 支持在 branches 中嵌套任意 WorkflowStep，因此依赖校验必须递归覆盖。
                self._collect_step_deps(list(step.branches), missing)
            elif isinstance(step, ConditionalStep):
                self._collect_step_deps(list(step.branches.values()), missing)
                if step.default is not None:
                    self._collect_step_deps([step.default], missing)
