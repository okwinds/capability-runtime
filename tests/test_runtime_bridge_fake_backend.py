from __future__ import annotations

"""离线回归：用 FakeChatBackend 驱动真实 SDK Agent loop（不 patch Agent 本体）。"""

from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Union

import pytest

from agent_sdk.llm.chat_sse import ChatStreamEvent

from agently_skills_runtime.config import RuntimeConfig
from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.protocol.capability import CapabilityKind, CapabilityResult, CapabilitySpec
from agently_skills_runtime.runtime import Runtime


class FakeChatBackend:
    """最小 ChatBackend：只回一个文本并 completed。"""

    async def stream_chat(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Any]] = None,
        temperature: Optional[float] = None,
    ) -> AsyncIterator[Any]:
        _ = model
        _ = messages
        _ = tools
        _ = temperature
        yield ChatStreamEvent(type="text_delta", text="ok")
        yield ChatStreamEvent(type="completed", finish_reason="stop")


@pytest.mark.asyncio
async def test_sdk_native_run_stream_yields_events_and_terminal_result(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    验收点：
    - 使用真实 agent_sdk.Agent loop
    - Runtime.run_stream 能先转发 AgentEvent，再产出 CapabilityResult
    """

    import agent_sdk.llm.openai_chat as openai_chat

    monkeypatch.setattr(openai_chat, "OpenAIChatCompletionsBackend", lambda *_args, **_kwargs: FakeChatBackend())

    rt = Runtime(RuntimeConfig(mode="sdk_native", workspace_root=tmp_path, preflight_mode="off"))
    rt.register(AgentSpec(base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A", description="say ok")))

    got_events = 0
    terminal: Optional[CapabilityResult] = None
    async for item in rt.run_stream("A", input={"x": 1}):
        if isinstance(item, CapabilityResult):
            terminal = item
        else:
            got_events += 1

    assert got_events > 0
    assert terminal is not None
    assert terminal.output == "ok"
    assert terminal.node_report is not None
    assert terminal.node_report.events_path is not None

