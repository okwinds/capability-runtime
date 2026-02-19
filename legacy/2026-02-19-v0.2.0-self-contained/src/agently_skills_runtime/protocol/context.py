"""
protocol/context.py

执行上下文：跨能力状态传递与调用链管理（递归深度守卫 + 映射表达式解析）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class RecursionLimitError(Exception):
    """嵌套深度超限错误。"""


@dataclass
class ExecutionContext:
    """
    执行上下文。

    参数：
    - run_id：本次运行唯一 ID。
    - parent_context：父上下文（可选）。
    - depth：当前深度（root 为 0）。
    - max_depth：允许的最大深度。
    - bag：共享数据字典（跨能力传递）。
    - step_outputs：步骤输出缓存（WorkflowAdapter 写入）。
    - call_chain：调用链（用于诊断）。
    """

    run_id: str
    parent_context: ExecutionContext | None = None
    depth: int = 0
    max_depth: int = 10
    bag: dict[str, Any] = field(default_factory=dict)
    step_outputs: dict[str, Any] = field(default_factory=dict)
    call_chain: list[str] = field(default_factory=list)

    def child(self, capability_id: str) -> ExecutionContext:
        """
        创建子上下文（depth+1，bag 浅拷贝；step_outputs 清空）。

        参数：
        - capability_id：即将进入执行的能力 ID（用于 call_chain）。

        返回：
        - 子 ExecutionContext

        异常：
        - RecursionLimitError：当 depth+1 > max_depth
        """

        next_depth = self.depth + 1
        if next_depth > self.max_depth:
            chain = self.call_chain + [capability_id]
            raise RecursionLimitError(f"Depth {next_depth} > max {self.max_depth}. Chain: {chain}")

        return ExecutionContext(
            run_id=self.run_id,
            parent_context=self,
            depth=next_depth,
            max_depth=self.max_depth,
            bag=dict(self.bag),
            step_outputs={},
            call_chain=self.call_chain + [capability_id],
        )

    def resolve_mapping(self, expression: str) -> Any:
        """
        解析映射表达式。

        支持：
        - "context.{key}"：bag[key]
        - "previous.{key}"：最后一个 step_output
        - "step.{step_id}.{key}"：step_outputs[step_id]
        - "literal.{value}"：字面量字符串（不做类型转换）
        - "item" / "item.{key}"：bag["__loop_item__"]

        参数：
        - expression：映射表达式字符串

        返回：
        - 解析结果；不存在时返回 None（未知前缀抛 ValueError）
        """

        parts = (expression or "").split(".", 1)
        prefix = parts[0]
        rest = parts[1] if len(parts) > 1 else ""

        if prefix == "context":
            return _deep_get(self.bag, rest)
        if prefix == "previous":
            last = self._last_step_output()
            return _deep_get(last, rest) if last is not None else None
        if prefix == "step":
            step_id, key = (rest.split(".", 1) + [""])[:2]
            out = self.step_outputs.get(step_id)
            return _deep_get(out, key) if out is not None else None
        if prefix == "literal":
            return rest
        if prefix == "item":
            item = self.bag.get("__loop_item__")
            if not rest:
                return item
            return _deep_get(item, rest) if item is not None else None

        raise ValueError(f"Unknown mapping prefix: {prefix!r}")

    def _last_step_output(self) -> Any:
        """
        取最后一个步骤输出（按 insertion-order）。

        返回：
        - 任意对象或 None
        """

        if not self.step_outputs:
            return None
        return list(self.step_outputs.values())[-1]


def _deep_get(obj: Any, dotted_key: str) -> Any:
    """
    从 dict 或对象属性中按点路径取值。

    参数：
    - obj：任意对象
    - dotted_key：点分隔路径；为空则返回 obj 本身

    返回：
    - 值或 None（路径不存在/类型不支持）
    """

    if not dotted_key:
        return obj

    current = obj
    for part in dotted_key.split("."):
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(part)
            continue
        if hasattr(current, part):
            current = getattr(current, part)
            continue
        return None
    return current

