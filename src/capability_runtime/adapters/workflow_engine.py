"""Workflow 引擎内部协议。"""
from __future__ import annotations

from typing import Any, AsyncIterator, Dict, Protocol, Union

from ..protocol.capability import CapabilityResult
from ..protocol.context import ExecutionContext
from ..protocol.workflow import WorkflowSpec
from ..services import RuntimeServices

# Workflow 轻量流式事件：默认给编排/UI 读取，不承担深审计职责。
WorkflowStreamEvent = Dict[str, Any]
WorkflowStreamItem = Union[WorkflowStreamEvent, CapabilityResult]


class WorkflowEngine(Protocol):
    """
    Workflow 引擎协议（内部使用）。

    约束：
    - 对外 API 仍由 Runtime 暴露；
    - 引擎可替换，但 execute/execute_stream 契约必须稳定。
    """

    async def execute(
        self,
        *,
        spec: WorkflowSpec,
        input: Dict[str, Any],
        context: ExecutionContext,
        services: RuntimeServices,
    ) -> CapabilityResult:
        """执行 Workflow（非流式）。"""

    async def execute_stream(
        self,
        *,
        spec: WorkflowSpec,
        input: Dict[str, Any],
        context: ExecutionContext,
        services: RuntimeServices,
    ) -> AsyncIterator[WorkflowStreamItem]:
        """执行 Workflow（流式）。"""
