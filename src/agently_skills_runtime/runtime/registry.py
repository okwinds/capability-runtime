"""能力注册表——所有 Spec 的中央存储和查询。"""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Union

from ..protocol.agent import AgentSpec
from ..protocol.capability import CapabilityKind, CapabilitySpec
from ..protocol.skill import SkillSpec
from ..protocol.workflow import ConditionalStep, LoopStep, ParallelStep, Step, WorkflowSpec

AnySpec = Union[SkillSpec, AgentSpec, WorkflowSpec]


def _get_base(spec: AnySpec) -> CapabilitySpec:
    """从具体 Spec 中提取公共 base。"""
    return spec.base


class CapabilityRegistry:
    """
    能力注册表。

    线程安全说明：当前为单线程设计（asyncio 单事件循环）。
    """

    def __init__(self) -> None:
        self._store: Dict[str, AnySpec] = {}

    def register(self, spec: AnySpec) -> None:
        """注册一个能力。重复注册同一 ID 会覆盖（last-write-wins）。"""
        base = _get_base(spec)
        self._store[base.id] = spec

    def get(self, capability_id: str) -> Optional[AnySpec]:
        """查找能力，不存在返回 None。"""
        return self._store.get(capability_id)

    def get_or_raise(self, capability_id: str) -> AnySpec:
        """查找能力，不存在抛 KeyError。"""
        spec = self.get(capability_id)
        if spec is None:
            raise KeyError(f"Capability not found: {capability_id!r}")
        return spec

    def list_all(self) -> List[AnySpec]:
        """列出所有已注册能力。"""
        return list(self._store.values())

    def list_by_kind(self, kind: CapabilityKind) -> List[AnySpec]:
        """列出指定种类的所有能力。"""
        return [s for s in self._store.values() if _get_base(s).kind == kind]

    def list_ids(self) -> List[str]:
        """列出所有已注册能力的 ID。"""
        return list(self._store.keys())

    def has(self, capability_id: str) -> bool:
        """检查能力是否已注册。"""
        return capability_id in self._store

    def unregister(self, capability_id: str) -> bool:
        """注销能力，返回是否存在并已删除。"""
        if capability_id in self._store:
            del self._store[capability_id]
            return True
        return False

    def validate_dependencies(self) -> List[str]:
        """
        校验所有能力的依赖是否已注册。

        检查范围：
        - AgentSpec.skills 中引用的 Skill ID
        - AgentSpec.collaborators / callable_workflows 中引用的能力 ID
        - WorkflowSpec 中所有 Step/LoopStep 的 capability.id
        - ParallelStep.branches 内的步骤
        - ConditionalStep.branches/default 内的步骤
        - SkillSpec.dispatch_rules 中引用的 target.id

        返回：缺失的 ID 列表（空列表表示全部满足）
        """
        missing: Set[str] = set()

        for spec in self._store.values():
            if isinstance(spec, AgentSpec):
                for skill_id in spec.skills:
                    if skill_id not in self._store:
                        missing.add(skill_id)
                for ref in spec.collaborators:
                    if ref.id not in self._store:
                        missing.add(ref.id)
                for ref in spec.callable_workflows:
                    if ref.id not in self._store:
                        missing.add(ref.id)

            elif isinstance(spec, WorkflowSpec):
                self._collect_step_deps(spec.steps, missing)

            elif isinstance(spec, SkillSpec):
                for rule in spec.dispatch_rules:
                    if rule.target.id not in self._store:
                        missing.add(rule.target.id)

        return sorted(missing)

    def _collect_step_deps(self, steps: list, missing: Set[str]) -> None:
        """递归收集步骤中的能力依赖。"""
        for step in steps:
            if isinstance(step, (Step, LoopStep)):
                if step.capability.id not in self._store:
                    missing.add(step.capability.id)
            elif isinstance(step, ParallelStep):
                for branch in step.branches:
                    if isinstance(branch, (Step, LoopStep)):
                        if branch.capability.id not in self._store:
                            missing.add(branch.capability.id)
            elif isinstance(step, ConditionalStep):
                for branch in step.branches.values():
                    if isinstance(branch, (Step, LoopStep)):
                        if branch.capability.id not in self._store:
                            missing.add(branch.capability.id)
                if step.default and isinstance(step.default, (Step, LoopStep)):
                    if step.default.capability.id not in self._store:
                        missing.add(step.default.capability.id)

    def find_skills_injecting_to(self, agent_id: str) -> List[SkillSpec]:
        """查找所有声明了 inject_to 包含指定 agent_id 的 SkillSpec。"""
        result = []
        for spec in self._store.values():
            if isinstance(spec, SkillSpec) and agent_id in spec.inject_to:
                result.append(spec)
        return result

