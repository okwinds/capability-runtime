from __future__ import annotations

"""执行上下文——跨能力状态传递和调用链管理。"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class RecursionLimitError(Exception):
    """嵌套深度超限。"""


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
    bag: Dict[str, Any] = field(default_factory=dict)
    step_outputs: Dict[str, Any] = field(default_factory=dict)
    # step_id -> {status, output, error, report}（面向编排的执行证据；不落盘）
    step_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    call_chain: List[str] = field(default_factory=list)

    def child(self, capability_id: str) -> ExecutionContext:
        """
        创建子上下文。

        行为：
        - depth + 1；超过 max_depth 抛 RecursionLimitError
        - bag 浅拷贝（子 context 可修改自己的 bag 而不影响父级）
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
            bag=dict(self.bag),
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
            key = parts[1] if len(parts) > 1 else None
            out = self.step_outputs.get(step_id)
            if key is None:
                return out
            if isinstance(out, dict):
                return out.get(key)
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
