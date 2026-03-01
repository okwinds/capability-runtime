from __future__ import annotations

"""ExecutionContext 单元测试。"""

import asyncio
from types import MappingProxyType

import pytest

from capability_runtime.protocol.context import ExecutionContext, RecursionLimitError


class TestResolveMapping:
    """resolve_mapping 6 种前缀全覆盖。"""

    def test_context_prefix(self):
        ctx = ExecutionContext(run_id="r1", bag={"name": "Alice", "age": 25})
        assert ctx.resolve_mapping("context.name") == "Alice"
        assert ctx.resolve_mapping("context.age") == 25
        assert ctx.resolve_mapping("context.missing") is None

    def test_previous_prefix(self):
        ctx = ExecutionContext(run_id="r1")
        ctx.step_outputs["s1"] = {"score": 80}
        ctx.step_outputs["s2"] = {"grade": "A"}
        # previous 指最后一个 step_output
        assert ctx.resolve_mapping("previous.grade") == "A"
        assert ctx.resolve_mapping("previous.missing") is None

    def test_previous_no_outputs(self):
        ctx = ExecutionContext(run_id="r1")
        assert ctx.resolve_mapping("previous.anything") is None

    def test_step_prefix_with_key(self):
        ctx = ExecutionContext(run_id="r1")
        ctx.step_outputs["plan"] = {"角色列表": ["A", "B", "C"]}
        assert ctx.resolve_mapping("step.plan.角色列表") == ["A", "B", "C"]
        assert ctx.resolve_mapping("step.plan.missing") is None
        assert ctx.resolve_mapping("step.nonexistent.key") is None

    def test_step_prefix_whole_output(self):
        ctx = ExecutionContext(run_id="r1")
        ctx.step_outputs["s1"] = {"x": 1, "y": 2}
        result = ctx.resolve_mapping("step.s1")
        assert result == {"x": 1, "y": 2}

    def test_literal_prefix(self):
        ctx = ExecutionContext(run_id="r1")
        assert ctx.resolve_mapping("literal.hello world") == "hello world"
        assert ctx.resolve_mapping("literal.") == ""

    def test_item_prefix(self):
        ctx = ExecutionContext(
            run_id="r1",
            bag={"__current_item__": {"name": "角色A", "type": "主角"}},
        )
        assert ctx.resolve_mapping("item") == {"name": "角色A", "type": "主角"}
        assert ctx.resolve_mapping("item.name") == "角色A"
        assert ctx.resolve_mapping("item.type") == "主角"
        assert ctx.resolve_mapping("item.missing") is None

    def test_item_no_current_item(self):
        ctx = ExecutionContext(run_id="r1")
        assert ctx.resolve_mapping("item") is None
        assert ctx.resolve_mapping("item.name") is None

    def test_unknown_prefix_returns_none(self):
        ctx = ExecutionContext(run_id="r1")
        assert ctx.resolve_mapping("unknown.key") is None
        assert ctx.resolve_mapping("") is None


class TestChild:
    """child() 递归深度控制。"""

    def test_child_increments_depth(self):
        parent = ExecutionContext(run_id="r1", depth=0, max_depth=5)
        child = parent.child("MA-013")
        assert child.depth == 1
        assert child.parent_context is parent
        assert child.call_chain == ["MA-013"]

    def test_child_inherits_bag_as_copy(self):
        parent = ExecutionContext(run_id="r1", bag={"key": "value"})
        child = parent.child("MA-013")
        assert child.bag["key"] == "value"
        assert isinstance(child.bag, MappingProxyType)
        # bag 不可直接写入：应抛 TypeError
        with pytest.raises(TypeError):
            child.bag["new_key"] = "new_value"  # type: ignore[index]

        # 正确写法：with_bag_overlay 返回新 context
        over = child.with_bag_overlay(new_key="new_value")
        assert over.bag["new_key"] == "new_value"
        assert "new_key" not in child.bag
        assert "new_key" not in parent.bag

    def test_child_has_empty_step_outputs(self):
        parent = ExecutionContext(run_id="r1")
        parent.step_outputs["s1"] = {"x": 1}
        child = parent.child("MA-013")
        assert child.step_outputs == {}

    def test_child_chain_accumulates(self):
        ctx = ExecutionContext(run_id="r1", max_depth=10)
        c1 = ctx.child("WF-001")
        c2 = c1.child("MA-013")
        c3 = c2.child("MA-014")
        assert c3.call_chain == ["WF-001", "MA-013", "MA-014"]
        assert c3.depth == 3

    def test_child_exceeds_max_depth(self):
        ctx = ExecutionContext(run_id="r1", max_depth=2)
        c1 = ctx.child("A")
        c2 = c1.child("B")
        with pytest.raises(RecursionLimitError, match="exceeds max 2"):
            c2.child("C")

    def test_child_exactly_at_max_depth(self):
        ctx = ExecutionContext(run_id="r1", max_depth=2)
        c1 = ctx.child("A")
        c2 = c1.child("B")
        # depth=2 == max_depth=2，刚好不超限
        assert c2.depth == 2
        # 再 child 才超限
        with pytest.raises(RecursionLimitError):
            c2.child("C")


class TestBagOverlay:
    def test_with_bag_overlay_returns_new_context(self):
        ctx = ExecutionContext(run_id="r1", bag={"a": 1})
        over = ctx.with_bag_overlay(b=2)

        assert over is not ctx
        assert ctx.bag == {"a": 1}
        assert over.bag == {"a": 1, "b": 2}
        assert isinstance(ctx.bag, MappingProxyType)
        assert isinstance(over.bag, MappingProxyType)

    def test_bag_cannot_be_written_directly(self):
        ctx = ExecutionContext(run_id="r1", bag={"a": 1})
        with pytest.raises(TypeError):
            ctx.bag["x"] = 1  # type: ignore[index]

    def test_with_bag_overlay_keeps_step_outputs_reference(self):
        ctx = ExecutionContext(run_id="r1", bag={"a": 1})
        ctx.step_outputs["s1"] = {"x": 1}
        over = ctx.with_bag_overlay(b=2)

        assert over.step_outputs is ctx.step_outputs
        assert over.step_results is ctx.step_results


class TestCancellationToken:
    def test_token_cancelled_flag(self):
        from capability_runtime.protocol.context import CancellationToken

        token = CancellationToken()
        assert token.is_cancelled is False
        token.cancel()
        assert token.is_cancelled is True

    @pytest.mark.asyncio
    async def test_token_wait_is_woken_by_cancel(self):
        from capability_runtime.protocol.context import CancellationToken

        token = CancellationToken()
        assert token.is_cancelled is False

        waiter = pytest.raises(asyncio.TimeoutError)
        # 先证明 wait() 会阻塞（没有 cancel 之前）。
        with waiter:
            await asyncio.wait_for(token.wait(), timeout=0.01)

        token.cancel()
        await asyncio.wait_for(token.wait(), timeout=0.1)

    def test_child_inherits_cancel_token(self):
        from capability_runtime.protocol.context import CancellationToken

        token = CancellationToken()
        parent = ExecutionContext(run_id="r1", cancel_token=token)
        child = parent.child("A")
        assert child.cancel_token is token
