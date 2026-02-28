"""回归：上游扩展点（Agent.register_tool）优先，旧版回退到 _extra_tools。"""
from __future__ import annotations

import pytest

from capability_runtime.adapters.upstream import register_agent_tool


def test_register_agent_tool_prefers_public_api_when_available() -> None:
    called = {"args": None}

    class A:
        def register_tool(self, spec, handler, override: bool = False) -> None:
            called["args"] = (spec, handler, override)

    agent = A()
    register_agent_tool(agent=agent, spec="S", handler="H", override=True)
    assert called["args"] == ("S", "H", True)


def test_register_agent_tool_falls_back_to_extra_tools_list() -> None:
    class A:
        def __init__(self) -> None:
            self._extra_tools = []

    agent = A()
    register_agent_tool(agent=agent, spec="S", handler="H", override=False)
    assert agent._extra_tools == [("S", "H")]


def test_register_agent_tool_raises_when_no_extension_point() -> None:
    class A:
        pass

    with pytest.raises(AttributeError, match="register_tool"):
        register_agent_tool(agent=A(), spec="S", handler="H", override=False)

