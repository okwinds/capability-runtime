"""场景回归：Host 侧 RAG 集成（pre-run 注入 + tool 调用证据链）。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from agent_sdk.core.contracts import AgentEvent
from agent_sdk.tools.protocol import ToolCall
from agent_sdk.tools.registry import ToolExecutionContext, ToolRegistry

import capability_runtime.bridge as runtime_mod
from capability_runtime.bridge import Runtime, RuntimeConfig
from capability_runtime.reporting.node_report import NodeReportBuilder


def _add_archive_backend_src_to_path() -> None:
    """把 archive web-prototype backend 的 `src/` 加入 `sys.path`。"""

    repo_root = Path(__file__).resolve().parents[2]
    backend_src = repo_root / "archive" / "projects" / "agently-skills-web-prototype" / "backend" / "src"
    if str(backend_src) not in sys.path:
        sys.path.insert(0, str(backend_src))


_add_archive_backend_src_to_path()

from agently_skills_web_backend.rag import (  # noqa: E402
    InMemoryRagProvider,
    RagToolDeps,
    build_rag_injected_messages,
    build_rag_meta,
    build_rag_retrieve_tool,
)


class _FakeRequester:
    """最小 Fake requester：只返回 `[DONE]`，用于离线 `run_async`。"""

    def generate_request_data(self):
        """返回与 Agently requester 兼容的最小 request_data。"""

        return type(
            "Req",
            (),
            {"data": {"messages": []}, "request_options": {}, "stream": True, "headers": {}, "client_options": {}, "request_url": "x"},
        )()

    async def request_model(self, request_data):
        """输出最小流式消息。"""

        _ = request_data
        yield ("message", "[DONE]")


def _patch_requester_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 bridge requester 工厂替换成离线 fake，避免触网。"""

    def fake_build(*, agently_agent: Any):
        _ = agently_agent
        return lambda: _FakeRequester()

    monkeypatch.setattr(runtime_mod, "build_openai_compatible_requester_factory", fake_build)


class _FakeAgent:
    """离线 fake SDK Agent：回放固定事件，并记录 `initial_history`。"""

    def __init__(self, *, events: List[AgentEvent]) -> None:
        """初始化事件序列。"""

        self._events = list(events)
        self.last_initial_history: Optional[List[Dict[str, Any]]] = None

    async def run_stream_async(self, task, *, run_id=None, initial_history=None):
        """回放事件流并记录调用参数。"""

        _ = task
        _ = run_id
        self.last_initial_history = initial_history
        for ev in self._events:
            yield ev


def _mk_runtime(monkeypatch: pytest.MonkeyPatch) -> Runtime:
    """构造用于离线场景回归的 runtime。"""

    _patch_requester_factory(monkeypatch)
    cfg = RuntimeConfig(
        workspace_root=Path("."),
        config_paths=[],
        preflight_mode="off",
    )
    return Runtime(agently_agent=object(), config=cfg)


def _collecting_ctx(*, events: List[AgentEvent]) -> ToolExecutionContext:
    """构造 ToolRegistry 执行上下文并把事件写入 `events`。"""

    return ToolExecutionContext(
        workspace_root=Path.cwd(),
        run_id="rag-tool-run",
        wal=None,
        executor=None,
        human_io=None,
        env=None,
        cancel_checker=None,
        redaction_values=None,
        emit_tool_events=True,
        event_sink=events.append,
        skills_manager=None,
        exec_sessions=None,
        web_search_provider=None,
        collab_manager=None,
    )


@pytest.mark.asyncio
async def test_pre_run_injection_meta_uses_minimal_disclosure(monkeypatch: pytest.MonkeyPatch) -> None:
    """场景 A：pre-run 注入后，`meta.rag` 必须只有最小披露字段。"""

    rt = _mk_runtime(monkeypatch)

    fake_events = [
        AgentEvent(type="run_started", ts="2026-02-10T00:00:00Z", run_id="r1", payload={}),
        AgentEvent(type="run_completed", ts="2026-02-10T00:00:01Z", run_id="r1", payload={"final_output": "ok", "events_path": "wal.jsonl"}),
    ]
    fake_agent = _FakeAgent(events=fake_events)
    monkeypatch.setattr(rt, "_get_or_create_agent", lambda: fake_agent)

    provider = InMemoryRagProvider.from_documents(
        [
            {"doc_id": "d1", "source": "kb://policy", "content": "审批流默认 fail-closed。"},
            {"doc_id": "d2", "source": "kb://guide", "content": "TriggerFlow tool 调用需要证据链。"},
        ]
    )
    rag_result = provider.retrieve(query="审批 流程 证据链", top_k=2)
    injected_messages = build_rag_injected_messages(query="审批 流程 证据链", rag_result=rag_result)
    rag_meta = build_rag_meta(mode="pre_run", query="审批 流程 证据链", top_k=2, rag_result=rag_result)

    out = await rt.run_async("请总结审批流策略", initial_history=injected_messages)
    out.node_report.meta["rag"] = rag_meta

    assert fake_agent.last_initial_history == injected_messages
    assert out.node_report.meta["rag"]["mode"] == "pre_run"
    first_query = out.node_report.meta["rag"]["queries"][0]
    assert first_query["query_sha256"]
    assert "query" not in first_query
    for chunk in first_query["chunks"]:
        assert "content" not in chunk


def test_tool_mode_registry_dispatch_records_rag_tool_and_redacts_content() -> None:
    """场景 B：tool 调用 `rag_retrieve` 进入 NodeReport，且默认不返回原文内容。"""

    provider = InMemoryRagProvider.from_documents(
        [
            {"doc_id": "d1", "source": "kb://ops", "content": "NodeReport 记录 tool_calls 证据。"},
            {"doc_id": "d2", "source": "kb://security", "content": "默认最小披露，不在 meta 落原文。"},
        ]
    )
    spec, handler = build_rag_retrieve_tool(deps=RagToolDeps(provider=provider))

    emitted: List[AgentEvent] = []
    registry = ToolRegistry(ctx=_collecting_ctx(events=emitted))
    registry.register(spec, handler)

    result = registry.dispatch(
        ToolCall(call_id="call_rag_1", name="rag_retrieve", args={"query": "NodeReport 证据链", "top_k": 2})
    )
    assert result.ok is True

    report = NodeReportBuilder().build(
        events=[
            AgentEvent(type="run_started", ts="2026-02-10T00:00:00Z", run_id="rag-tool-run", payload={}),
            *emitted,
            AgentEvent(
                type="run_completed",
                ts="2026-02-10T00:00:01Z",
                run_id="rag-tool-run",
                payload={"final_output": "ok", "events_path": "wal.jsonl"},
            ),
        ]
    )
    rag_calls = [call for call in report.tool_calls if call.name == "rag_retrieve"]
    assert len(rag_calls) == 1
    chunks = (rag_calls[0].data or {}).get("chunks") or []
    assert chunks
    for chunk in chunks:
        assert "content" not in chunk
