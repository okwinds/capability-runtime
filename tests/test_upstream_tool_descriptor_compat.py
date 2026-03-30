from __future__ import annotations

import pytest

from skills_runtime.tools.protocol import ToolSpec

from capability_runtime.config import CustomTool
from capability_runtime.sdk_lifecycle import _register_custom_tool_compat


class _NewSignatureAgent:
    def __init__(self) -> None:
        self.calls = []

    def register_tool(self, spec, handler, *, override: bool = False, descriptor=None) -> None:
        self.calls.append((spec.name, bool(override), descriptor, handler))


class _OldSignatureAgent:
    def __init__(self) -> None:
        self.calls = []

    def register_tool(self, spec, handler, *, override: bool = False) -> None:
        self.calls.append((spec.name, bool(override), handler))


class _BrokenOldSignatureAgent:
    def register_tool(self, spec, handler, *, override: bool = False) -> None:
        _ = (spec, handler, override)
        raise RuntimeError("register boom")


def _tool(descriptor=None) -> CustomTool:
    spec = ToolSpec(
        name="demo_tool",
        description="demo",
        parameters={"type": "object", "properties": {}, "required": []},
    )

    def handler(call, ctx):
        _ = (call, ctx)
        return {"ok": True}

    return CustomTool(spec=spec, handler=handler, override=True, descriptor=descriptor)


def test_register_custom_tool_compat_passes_descriptor_when_supported() -> None:
    agent = _NewSignatureAgent()
    tool = _tool(descriptor={"policy": "safe"})

    diagnostics = _register_custom_tool_compat(agent, tool)

    assert agent.calls[0][:3] == ("demo_tool", True, {"policy": "safe"})
    assert diagnostics == {
        "descriptor_requested": True,
        "descriptor_supported": True,
        "descriptor_applied": True,
    }


def test_register_custom_tool_compat_falls_back_when_descriptor_not_supported() -> None:
    agent = _OldSignatureAgent()
    tool = _tool(descriptor={"policy": "safe"})

    diagnostics = _register_custom_tool_compat(agent, tool)

    assert agent.calls[0][:2] == ("demo_tool", True)
    assert diagnostics == {
        "descriptor_requested": True,
        "descriptor_supported": False,
        "descriptor_applied": False,
    }


def test_register_custom_tool_compat_reports_descriptor_not_requested() -> None:
    agent = _NewSignatureAgent()
    tool = _tool(descriptor=None)

    diagnostics = _register_custom_tool_compat(agent, tool)

    assert agent.calls[0][:3] == ("demo_tool", True, None)
    assert diagnostics == {
        "descriptor_requested": False,
        "descriptor_supported": True,
        "descriptor_applied": False,
    }


def test_register_custom_tool_compat_preserves_old_signature_failure() -> None:
    with pytest.raises(RuntimeError, match="register boom"):
        _register_custom_tool_compat(_BrokenOldSignatureAgent(), _tool(descriptor={"policy": "safe"}))
