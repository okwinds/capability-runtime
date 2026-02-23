"""Agent 适配器：AgentSpec → Bridge Runtime 执行。"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ..protocol.agent import AgentSpec
from ..protocol.capability import CapabilityResult, CapabilityStatus
from ..protocol.context import ExecutionContext


class AgentAdapter:
    """
    Agent 适配器。

    参数：
    - runner: 异步执行函数。签名：
        async def runner(task: str, *, initial_history: Optional[List] = None) -> Any
      通常传入 AgentlySkillsRuntime.run_async。
      也可以传入任何兼容签名的 async callable（方便测试）。
    """

    def __init__(
        self,
        *,
        runner: Optional[Callable[..., Awaitable[Any]]] = None,
    ):
        self._runner = runner

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
        1. 构造 task 文本（prompt_template + input + output_schema）
        2. 构造 initial_history（如有 system_prompt）
        3. 委托 runner 执行
        4. 包装返回值为 CapabilityResult

        说明：
        - 本仓库不再提供 Skill 原语与注入机制（方案 2）。
        - skills 的发现/mention/sources/preflight/tools/approvals/WAL 由上游 `agent_sdk` 负责。
        """
        if self._runner is None:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=(
                    "AgentAdapter: no runner injected. "
                    "Inject AgentlySkillsRuntime.run_async or a compatible async callable."
                ),
            )

        # 1) 构造 task 文本
        task = self._build_task(spec=spec, input=input)

        # 2) 构造 initial_history
        initial_history = None
        if spec.system_prompt:
            initial_history = [{"role": "system", "content": spec.system_prompt}]

        # 3) 委托 runner 执行
        try:
            result = await self._runner(task, initial_history=initial_history)
        except Exception as exc:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                error=f"Agent execution error: {exc}",
            )

        # 4) 包装返回值
        return self._wrap_result(result)

    def _build_task(
        self,
        *,
        spec: AgentSpec,
        input: Dict[str, Any],
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
