"""Agent 适配器：AgentSpec → Bridge Runtime 执行。"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ..protocol.agent import AgentSpec
from ..protocol.capability import CapabilityResult, CapabilityStatus
from ..protocol.context import ExecutionContext
from ..protocol.skill import SkillSpec


class AgentAdapter:
    """
    Agent 适配器。

    参数：
    - runner: 异步执行函数。签名：
        async def runner(task: str, *, initial_history: Optional[List] = None) -> Any
      通常传入 AgentlySkillsRuntime.run_async。
      也可以传入任何兼容签名的 async callable（方便测试）。
    - skill_content_loader: 可选的 Skill 内容加载函数。签名：
        def loader(spec: SkillSpec) -> str
      如果不提供，则 skill 注入使用 spec.source 字段作为内容。
    """

    def __init__(
        self,
        *,
        runner: Optional[Callable[..., Awaitable[Any]]] = None,
        skill_content_loader: Optional[Callable[[SkillSpec], str]] = None,
    ):
        self._runner = runner
        self._skill_content_loader = skill_content_loader

    async def execute(
        self,
        *,
        spec: AgentSpec,
        input: Dict[str, Any],
        context: ExecutionContext,
        runtime: Any,  # CapabilityRuntime（避免循环 import）
    ) -> CapabilityResult:
        """
        执行 AgentSpec。

        流程：
        1. 合并 Skills（spec.skills + inject_to 匹配）
        2. 加载 Skill 内容
        3. 构造 task 文本（prompt_template + input + skills + output_schema）
        4. 构造 initial_history（如有 system_prompt）
        5. 委托 runner 执行
        6. 包装返回值为 CapabilityResult
        """
        if self._runner is None:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=(
                    "AgentAdapter: no runner injected. "
                    "Inject AgentlySkillsRuntime.run_async or a compatible async callable."
                ),
            )

        # 1) 合并 Skills（显式 skills + inject_to）
        skill_ids = list(spec.skills)
        if hasattr(runtime, "registry"):
            injecting_skills = runtime.registry.find_skills_injecting_to(spec.base.id)
            for s in injecting_skills:
                if s.base.id not in skill_ids:
                    skill_ids.append(s.base.id)

        # 2) 加载 Skill 内容
        skill_contents: List[str] = []
        for sid in skill_ids:
            if hasattr(runtime, "registry"):
                skill_spec = runtime.registry.get(sid)
                if isinstance(skill_spec, SkillSpec):
                    if self._skill_content_loader:
                        try:
                            content = self._skill_content_loader(skill_spec)
                        except Exception:
                            content = skill_spec.source
                    else:
                        content = skill_spec.source
                    skill_contents.append(f"[Skill: {skill_spec.base.name}]\n{content}")

        # 3) 构造 task 文本
        task = self._build_task(spec=spec, input=input, skill_contents=skill_contents)

        # 4) 构造 initial_history
        initial_history = None
        if spec.system_prompt:
            initial_history = [{"role": "system", "content": spec.system_prompt}]

        # 5) 委托 runner 执行
        try:
            result = await self._runner(task, initial_history=initial_history)
        except Exception as exc:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"Agent execution error: {exc}",
            )

        # 6) 包装返回值
        return self._wrap_result(result)

    def _build_task(
        self,
        *,
        spec: AgentSpec,
        input: Dict[str, Any],
        skill_contents: List[str],
    ) -> str:
        """从 AgentSpec + input 构造 task 文本。"""
        parts: List[str] = []

        # prompt_template 优先
        if spec.prompt_template:
            try:
                task_text = spec.prompt_template.format(**input)
                parts.append(task_text)
            except KeyError:
                parts.append(spec.prompt_template)
                parts.append(
                    f"\n输入参数:\n{json.dumps(input, ensure_ascii=False, indent=2)}"
                )
        else:
            if "task" in input:
                parts.append(str(input["task"]))
            else:
                parts.append(json.dumps(input, ensure_ascii=False, indent=2))

        # 注入 Skills
        if skill_contents:
            parts.append("\n\n--- 参考资料 ---")
            parts.extend(skill_contents)

        # 输出 schema 提示
        if spec.output_schema and spec.output_schema.fields:
            parts.append("\n\n请按以下格式输出 JSON：")
            schema_desc = json.dumps(
                {k: f"({v})" for k, v in spec.output_schema.fields.items()},
                ensure_ascii=False,
                indent=2,
            )
            parts.append(schema_desc)

        return "\n".join(parts)

    def _wrap_result(self, result: Any) -> CapabilityResult:
        """把桥接层返回值包装为 CapabilityResult。"""
        # 兼容 NodeResultV2（bridge.py 的返回值）
        if hasattr(result, "node_report"):
            nr = result.node_report
            output = getattr(result, "final_output", None)
            if output is None and hasattr(nr, "meta"):
                output = nr.meta.get("final_output")
            node_status = getattr(nr, "status", None)
            node_reason = getattr(nr, "reason", None)

            # NodeReport 是控制面强结构：success/failed/incomplete/needs_approval。
            # CapabilityStatus 是运行时统一状态：pending/running/success/failed/cancelled。
            #
            # 约束：
            # - 不能把 needs_approval/incomplete 折叠成 FAILED（否则编排层会误判并丢失语义）；
            # - FAILED 仅用于“明确失败”；其它非 success 的状态通过 report 暴露更细粒度语义。
            if node_status == "success":
                status = CapabilityStatus.SUCCESS
            elif node_status == "failed":
                status = CapabilityStatus.FAILED
            elif node_status == "needs_approval":
                status = CapabilityStatus.PENDING
            elif node_status == "incomplete":
                # incomplete 可能来自 cancel/budget/no-progress 等。
                status = CapabilityStatus.CANCELLED if node_reason == "cancelled" else CapabilityStatus.PENDING
            else:
                # 未知状态：保守降级为 FAILED，避免 silent success。
                status = CapabilityStatus.FAILED

            error = node_reason if status == CapabilityStatus.FAILED else None
            return CapabilityResult(
                status=status,
                output=output,
                error=error,
                report=nr,
            )

        # 兼容普通返回值
        if isinstance(result, str):
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output=result)
        if isinstance(result, dict):
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output=result)

        return CapabilityResult(status=CapabilityStatus.SUCCESS, output=result)
