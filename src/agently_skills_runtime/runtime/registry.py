"""
runtime/registry.py

能力注册表：注册、发现与依赖校验（含 Workflow steps 的递归扫描）。
"""

from __future__ import annotations

from typing import Iterable, Union

from ..protocol.agent import AgentSpec
from ..protocol.capability import CapabilityKind
from ..protocol.skill import SkillSpec
from ..protocol.workflow import ConditionalStep, LoopStep, ParallelStep, Step, WorkflowSpec, WorkflowStep

AnySpec = Union[SkillSpec, AgentSpec, WorkflowSpec]


class CapabilityRegistry:
    """
    能力注册表。

    行为：
    - register(spec)：注册/覆盖（同 ID 覆盖）。
    - get(id)：获取（不存在返回 None）。
    - get_or_raise(id)：获取（不存在抛 KeyError）。
    - list_by_kind(kind)：按 kind 过滤。
    - validate_dependencies()：校验所有引用的能力是否已注册，返回错误字符串列表。
    """

    def __init__(self) -> None:
        """创建空注册表。"""

        self._items: dict[str, AnySpec] = {}

    def register(self, spec: AnySpec) -> None:
        """
        注册能力声明（同 ID 覆盖）。

        参数：
        - spec：SkillSpec / AgentSpec / WorkflowSpec
        """

        self._items[spec.base.id] = spec

    def get(self, capability_id: str) -> AnySpec | None:
        """
        获取能力声明。

        参数：
        - capability_id：能力 ID

        返回：
        - spec 或 None
        """

        return self._items.get(capability_id)

    def get_or_raise(self, capability_id: str) -> AnySpec:
        """
        获取能力声明（不存在抛 KeyError）。

        参数：
        - capability_id：能力 ID

        返回：
        - spec

        异常：
        - KeyError：未注册
        """

        spec = self.get(capability_id)
        if spec is None:
            raise KeyError(capability_id)
        return spec

    def list_by_kind(self, kind: CapabilityKind) -> list[AnySpec]:
        """
        列出指定 kind 的能力声明。

        参数：
        - kind：CapabilityKind

        返回：
        - spec 列表
        """

        return [spec for spec in self._items.values() if spec.base.kind == kind]

    def validate_dependencies(self) -> list[str]:
        """
        校验所有引用的能力是否已注册。

        返回：
        - 错误字符串列表；空表示通过。
        """

        errors: list[str] = []
        missing: set[str] = set()

        def require(target_id: str, *, by: str, detail: str) -> None:
            if not target_id or target_id in self._items:
                return
            key = f"{target_id} (by={by}, detail={detail})"
            if key in missing:
                return
            missing.add(key)
            errors.append(f"missing dependency: {key}")

        for spec in self._items.values():
            by = spec.base.id
            if isinstance(spec, AgentSpec):
                for sid in spec.skills:
                    require(sid, by=by, detail="AgentSpec.skills")
                for ref in spec.collaborators:
                    require(ref.id, by=by, detail="AgentSpec.collaborators")
                for ref in spec.callable_workflows:
                    require(ref.id, by=by, detail="AgentSpec.callable_workflows")
            elif isinstance(spec, WorkflowSpec):
                for ref_id in self._iter_workflow_refs(spec.steps):
                    require(ref_id, by=by, detail="WorkflowSpec.steps")
            elif isinstance(spec, SkillSpec):
                for rule in spec.dispatch_rules:
                    require(rule.target.id, by=by, detail="SkillSpec.dispatch_rules")

        return errors

    def _iter_workflow_refs(self, steps: Iterable[WorkflowStep]) -> Iterable[str]:
        """
        递归提取 Workflow 中引用的 capability id。

        参数：
        - steps：WorkflowStep 序列

        返回：
        - capability id 的迭代器
        """

        for step in steps:
            yield from self._iter_step_refs(step)

    def _iter_step_refs(self, step: WorkflowStep) -> Iterable[str]:
        """
        递归提取单个 WorkflowStep 中引用的 capability id。

        参数：
        - step：WorkflowStep

        返回：
        - capability id 的迭代器
        """

        if isinstance(step, Step):
            yield step.capability.id
            return
        if isinstance(step, LoopStep):
            yield step.capability.id
            return
        if isinstance(step, ParallelStep):
            for branch in step.branches:
                yield from self._iter_step_refs(branch)
            return
        if isinstance(step, ConditionalStep):
            for branch in step.branches.values():
                yield from self._iter_step_refs(branch)
            if step.default is not None:
                yield from self._iter_step_refs(step.default)
            return

        raise TypeError(f"Unknown WorkflowStep: {type(step).__name__}")

