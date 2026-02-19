"""Skill 适配器：SkillSpec → 内容加载 + 可选 dispatch。"""
from __future__ import annotations

import os
from typing import Any, Dict

from ..protocol.capability import CapabilityResult, CapabilityStatus
from ..protocol.context import ExecutionContext
from ..protocol.skill import SkillSpec


class SkillAdapter:
    """
    Skill 适配器。

    行为：
    1. 加载 Skill 内容（file/inline/uri）
    2. 检查 dispatch_rules（Phase 3 仅做简单条件评估）
    3. 返回内容作为 output
    """

    def __init__(self, *, workspace_root: str = "."):
        self._workspace_root = workspace_root

    async def execute(
        self,
        *,
        spec: SkillSpec,
        input: Dict[str, Any],
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """执行 SkillSpec。"""
        # 1) 加载内容
        try:
            content = self._load_content(spec)
        except Exception as exc:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"Skill content load error: {exc}",
            )

        # 2) 检查 dispatch_rules
        dispatched_results = []
        for rule in spec.dispatch_rules:
            if self._evaluate_condition(rule.condition, context):
                try:
                    target_spec = runtime.registry.get_or_raise(rule.target.id)
                    result = await runtime._execute(target_spec, input=input, context=context)
                    dispatched_results.append(
                        {"target": rule.target.id, "result": result.output}
                    )
                except Exception as exc:
                    dispatched_results.append({"target": rule.target.id, "error": str(exc)})

        return CapabilityResult(
            status=CapabilityStatus.SUCCESS,
            output=content,
            metadata={"dispatched": dispatched_results} if dispatched_results else {},
        )

    def _load_content(self, spec: SkillSpec) -> str:
        """加载 Skill 内容。"""
        if spec.source_type == "inline":
            return spec.source
        if spec.source_type == "file":
            path = os.path.join(self._workspace_root, spec.source)
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        if spec.source_type == "uri":
            raise NotImplementedError(
                "URI loading requires allowlist authorization (safe-by-default)"
            )
        raise ValueError(f"Unknown source_type: {spec.source_type}")

    @staticmethod
    def _evaluate_condition(condition: str, context: ExecutionContext) -> bool:
        """Phase 3: 简单条件评估——检查 context bag 中 key 是否存在且 truthy。"""
        value = context.bag.get(condition)
        return bool(value)

