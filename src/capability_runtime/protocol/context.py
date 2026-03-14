from __future__ import annotations

"""执行上下文——跨能力状态传递和调用链管理。"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Dict, List, Optional


class RecursionLimitError(Exception):
    """嵌套深度超限。"""


class CancellationToken:
    """协作取消 token（不强制打断正在运行的步骤）。"""

    def __init__(self) -> None:
        import asyncio

        self._event = asyncio.Event()

    @property
    def is_cancelled(self) -> bool:
        """是否已被标记为取消。"""

        return self._event.is_set()

    def cancel(self) -> None:
        """标记为取消。"""

        self._event.set()

    async def wait(self) -> None:
        """等待取消发生。"""

        await self._event.wait()


@dataclass
class ExecutionContext:
    """
    执行上下文。

    参数：
    - run_id: 顶层运行 ID
    - parent_context: 父上下文（用于追溯调用链）
    - depth: 当前嵌套深度（从 0 开始）
    - max_depth: 最大嵌套深度
    - guards: per-run 执行守卫（如全局 loop 熔断计数器）
    - bag: 全局数据袋（浅拷贝传递）
    - step_outputs: 当前层级的步骤输出缓存（step_id → output）
    - call_chain: 调用链记录（能力 ID 列表）
    """

    run_id: str
    parent_context: Optional[ExecutionContext] = None
    depth: int = 0
    max_depth: int = 10
    guards: Any = None
    cancel_token: Optional[CancellationToken] = None
    bag: MappingProxyType[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    step_outputs: Dict[str, Any] = field(default_factory=dict)
    # step_id -> {status, output, error, report}（面向编排的执行证据；不落盘）
    step_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    call_chain: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """
        运行时强约束：bag 必须为不可变映射（MappingProxyType）。

        说明：
        - 调用方（包括 adapters/engines/tests）可能仍传入 dict；
        - 这里统一转换为 MappingProxyType(dict(...))，保证 `context.bag[k] = v` 会抛 TypeError。
        """

        if isinstance(self.bag, MappingProxyType):
            return
        if isinstance(self.bag, Mapping):
            self.bag = MappingProxyType(dict(self.bag))
            return
        self.bag = MappingProxyType({})

    def with_bag_overlay(self, **updates: Any) -> ExecutionContext:
        """
        返回带 bag 覆盖的新 ExecutionContext（不修改原对象）。

        设计目标：
        - 用于 workflow_id/step_id/branch_id 等"临时 hint"注入；
        - 共享 step_outputs/step_results 引用，保证执行证据链可持续累积；
        - bag 为不可变映射，所有修改必须通过 overlay 创建新 context。

        并发安全警告：
        - 本方法共享 step_outputs 引用（顺序执行设计）；
        - 并发分支（如 ParallelStep）必须用 `ExecutionContext(step_outputs=dict(...))` 显式创建副本。
        """

        base = dict(self.bag)
        base.update(updates)
        return ExecutionContext(
            run_id=self.run_id,
            parent_context=self.parent_context,
            depth=self.depth,
            max_depth=self.max_depth,
            guards=self.guards,
            cancel_token=self.cancel_token,
            bag=MappingProxyType(base),
            step_outputs=self.step_outputs,
            step_results=self.step_results,
            call_chain=self.call_chain,
        )

    def with_guards(self, guards: Any) -> ExecutionContext:
        """
        返回带有新 guards 的 ExecutionContext 副本。

        设计目标：
        - 确保 per-run guards 隔离，避免计数器跨 run 串扰；
        - 复制可变容器（step_outputs/step_results/call_chain），避免共享引用。

        参数：
        - guards：新的 ExecutionGuards 实例
        """

        return ExecutionContext(
            run_id=self.run_id,
            parent_context=self.parent_context,
            depth=self.depth,
            max_depth=self.max_depth,
            guards=guards,
            cancel_token=self.cancel_token,
            bag=self.bag,
            step_outputs=dict(self.step_outputs),
            step_results=dict(self.step_results),
            call_chain=list(self.call_chain),
        )

    def child(self, capability_id: str) -> ExecutionContext:
        """
        创建子上下文。

        行为：
        - depth + 1；超过 max_depth 抛 RecursionLimitError
        - bag 生成快照（不可变映射视图；修改需通过 with_bag_overlay 返回新 context）
        - step_outputs 清空（子 context 有独立的步骤输出空间）
        - call_chain 追加当前 capability_id
        """

        new_depth = self.depth + 1
        if new_depth > self.max_depth:
            raise RecursionLimitError(
                f"Recursion depth {new_depth} exceeds max {self.max_depth}. "
                f"Call chain: {self.call_chain + [capability_id]}"
            )
        return ExecutionContext(
            run_id=self.run_id,
            parent_context=self,
            depth=new_depth,
            max_depth=self.max_depth,
            guards=self.guards,
            cancel_token=self.cancel_token,
            bag=MappingProxyType(dict(self.bag)),
            step_outputs={},
            step_results={},
            call_chain=self.call_chain + [capability_id],
        )

    def resolve_mapping(self, expression: str) -> Any:
        """
        解析映射表达式，从 context 中提取数据。

        支持：
        - "context.{key}" → self.bag[key]
        - "previous.{key}" → 最后一个 step_output 的 [key]
        - "step.{step_id}.{key}" → self.step_outputs[step_id][key]
        - "step.{step_id}" → self.step_outputs[step_id]（整体）
        - "result.{step_id}" → self.step_results[step_id]（整体）
        - "result.{step_id}.status" → self.step_results[step_id]["status"]
        - "result.{step_id}.report.status" → self.step_results[step_id]["report"].status（若存在）
        - "literal.{value}" → 字面量字符串
        - "item" → self.bag["__current_item__"]
        - "item.{key}" → self.bag["__current_item__"][key]

        找不到时返回 None（不抛异常）。
        """

        def _resolve_one(obj: Any, key: str) -> Any:
            """对 dict/对象做一层 key/attribute 解析；取不到返回 None。"""

            if obj is None:
                return None
            if isinstance(obj, dict):
                return obj.get(key)
            return getattr(obj, key, None)

        if expression.startswith("context."):
            key = expression[len("context.") :]
            return self.bag.get(key)

        if expression.startswith("previous."):
            key = expression[len("previous.") :]
            if not self.step_outputs:
                return None
            last_key = list(self.step_outputs.keys())[-1]
            last_out = self.step_outputs[last_key]
            if isinstance(last_out, dict):
                return last_out.get(key)
            return None

        if expression.startswith("step."):
            rest = expression[len("step.") :]
            parts = rest.split(".", 1)
            step_id = parts[0]
            step_key = parts[1] if len(parts) > 1 else None
            out = self.step_outputs.get(step_id)
            if step_key is None:
                return out
            if isinstance(out, dict):
                return out.get(step_key)
            return None

        if expression.startswith("result."):
            rest = expression[len("result.") :]
            parts = rest.split(".")
            step_id = parts[0]
            cur: Any = self.step_results.get(step_id)
            for key in parts[1:]:
                cur = _resolve_one(cur, key)
            return cur

        if expression.startswith("literal."):
            return expression[len("literal.") :]

        if expression == "item":
            return self.bag.get("__current_item__")

        if expression.startswith("item."):
            key = expression[len("item.") :]
            item = self.bag.get("__current_item__")
            if isinstance(item, dict):
                return item.get(key)
            return None

        return None
