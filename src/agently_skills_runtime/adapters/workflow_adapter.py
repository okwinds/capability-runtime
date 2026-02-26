"""Workflow 适配器：内部委托 WorkflowEngine。"""
from __future__ import annotations

from typing import Any, Dict

from ..protocol.capability import CapabilityResult
from ..protocol.context import ExecutionContext
from ..protocol.workflow import WorkflowSpec
from .triggerflow_workflow_engine import TriggerFlowWorkflowEngine


class WorkflowAdapter:
    """
    Workflow 适配器（内部组织层）。

    说明：
    - 对外协议仍以 `WorkflowSpec` 为准；
    - 内部统一委托 `TriggerFlowWorkflowEngine`，避免主线继续维护两套逻辑。
    """

    def __init__(self) -> None:
        self._engine = TriggerFlowWorkflowEngine()

    async def execute(
        self,
        *,
        spec: WorkflowSpec,
        input: Dict[str, Any],
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """执行 WorkflowSpec（非流式）。"""

        return await self._engine.execute(spec=spec, input=input, context=context, runtime=runtime)
