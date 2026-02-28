from __future__ import annotations

import pytest

from capability_runtime.protocol.context import ExecutionContext, RecursionLimitError


class Obj:
    def __init__(self) -> None:
        self.attr = {"k": "v"}


def test_child_depth_and_chain() -> None:
    ctx = ExecutionContext(run_id="r", max_depth=2, bag={"a": 1})
    child = ctx.child("cap-A")
    assert child.depth == 1
    assert child.parent_context is ctx
    assert child.bag == {"a": 1}
    assert child.call_chain == ["cap-A"]


def test_child_recursion_limit() -> None:
    ctx = ExecutionContext(run_id="r", max_depth=0)
    with pytest.raises(RecursionLimitError):
        _ = ctx.child("cap-A")


def test_resolve_mapping_context_prefix() -> None:
    ctx = ExecutionContext(run_id="r", bag={"task": {"title": "x"}})
    assert ctx.resolve_mapping("context.task.title") == "x"


def test_resolve_mapping_literal_prefix() -> None:
    ctx = ExecutionContext(run_id="r")
    assert ctx.resolve_mapping("literal.hello") == "hello"


def test_resolve_mapping_previous_prefix_empty_returns_none() -> None:
    ctx = ExecutionContext(run_id="r")
    assert ctx.resolve_mapping("previous.any") is None


def test_resolve_mapping_step_prefix_missing_returns_none() -> None:
    ctx = ExecutionContext(run_id="r", step_outputs={})
    assert ctx.resolve_mapping("step.s1.x") is None


def test_resolve_mapping_item_prefix_forms() -> None:
    ctx = ExecutionContext(run_id="r", bag={"__loop_item__": {"x": 1}})
    assert ctx.resolve_mapping("item") == {"x": 1}
    assert ctx.resolve_mapping("item.x") == 1


def test_deep_get_object_attr() -> None:
    ctx = ExecutionContext(run_id="r", bag={"obj": Obj()})
    assert ctx.resolve_mapping("context.obj.attr.k") == "v"


def test_resolve_mapping_unknown_prefix_raises() -> None:
    ctx = ExecutionContext(run_id="r")
    with pytest.raises(ValueError):
        _ = ctx.resolve_mapping("unknown.x")

