"""能力注册表——所有 Spec 的中央存储和查询。"""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Union

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

    def register(self, spec: AnySpec) -> None:
        """
        注册一个能力。

        参数：
        - spec：能力声明（AgentSpec/WorkflowSpec）

        说明：
        - 重复注册同一 ID 会覆盖（last-write-wins）。
        """

        base = _get_base(spec)
        self._store[base.id] = spec

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
            return True
        return False

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
