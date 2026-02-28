from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Optional

import pytest

from skills_runtime.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from skills_runtime.llm.protocol import ChatRequest
from skills_runtime.safety.approvals import ApprovalDecision, ApprovalProvider, ApprovalRequest

from capability_runtime import (
    AgentSpec,
    CapabilityKind,
    CapabilityRef,
    CapabilitySpec,
    ParallelStep,
    Runtime,
    RuntimeConfig,
    Step,
    WorkflowSpec,
)
from capability_runtime.ui_events.v1 import StreamLevel


class _ApproveAll(ApprovalProvider):
    async def request_approval(self, *, request: ApprovalRequest, timeout_ms: Optional[int] = None) -> ApprovalDecision:
        _ = (request, timeout_ms)
        return ApprovalDecision.APPROVED


class _DeterministicToolBackend:
    """
    并行安全的 fake backend：
    - 每个“首轮”请求（未包含 tool result message）都会触发一次 tool_calls；
    - 任何包含 tool result message 的后续请求都会直接返回文本完成；
    - call_id 由自增计数生成，确保并行两路不会抢到同一个序列导致“单分支两次 tool_calls”。
    """

    def __init__(self, *, patch_text: str) -> None:
        self._patch_text = patch_text
        self._lock = asyncio.Lock()
        self._counter = 0

    async def stream_chat(self, request: ChatRequest):
        has_tool_result = any(
            isinstance(m, dict) and str(m.get("role") or "") in {"tool", "function"} for m in (request.messages or [])
        )
        if has_tool_result:
            yield ChatStreamEvent(type="text_delta", text="done")
            yield ChatStreamEvent(type="completed", finish_reason="stop")
            return

        async with self._lock:
            self._counter += 1
            call_id = f"c{self._counter}"

        yield ChatStreamEvent(
            type="tool_calls",
            tool_calls=[LlmToolCall(call_id=call_id, name="apply_patch", args={"input": self._patch_text})],
            finish_reason="tool_calls",
        )
        yield ChatStreamEvent(type="completed", finish_reason="tool_calls")


@pytest.mark.asyncio
async def test_same_workflow_spec_runs_twice_in_parallel_emits_distinct_workflow_instance_ids(tmp_path: Path) -> None:
    patch_text = "\n".join(["*** Begin Patch", "*** Add File: hello.txt", "+hello", "*** End Patch", ""]) + "\n"
    backend = _DeterministicToolBackend(patch_text=patch_text)

    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=tmp_path,
            sdk_config_paths=[],
            preflight_mode="off",
            sdk_backend=backend,
            approval_provider=_ApproveAll(),
        )
    )

    rt.register(AgentSpec(base=CapabilitySpec(id="agent.ui", kind=CapabilityKind.AGENT, name="AgentUI", description="离线：调用 apply_patch。")))
    rt.register(
        WorkflowSpec(
            base=CapabilitySpec(id="wf.child", kind=CapabilityKind.WORKFLOW, name="WFChild", description="child wf"),
            steps=[Step(id="child.s1", capability=CapabilityRef(id="agent.ui"))],
        )
    )
    rt.register(
        WorkflowSpec(
            base=CapabilitySpec(id="wf.root", kind=CapabilityKind.WORKFLOW, name="WFRoot", description="并行执行同一 child workflow"),
            steps=[
                ParallelStep(
                    id="p1",
                    branches=[
                        Step(id="b1", capability=CapabilityRef(id="wf.child")),
                        Step(id="b2", capability=CapabilityRef(id="wf.child")),
                    ],
                )
            ],
        )
    )

    out: List = []
    async for ev in rt.run_ui_events("wf.root", input={}, level=StreamLevel.UI):
        out.append(ev)
        if ev.type == "run.status" and ev.data.get("status") != "running":
            break

    tool_events = [e for e in out if e.type == "tool.requested"]
    assert len(tool_events) == 2

    branches = []
    child_workflow_instance_ids: List[str] = []
    for e in tool_events:
        branches.extend([seg.id for seg in e.path if seg.kind == "branch"])
        segs = [
            seg
            for seg in e.path
            if seg.kind == "workflow"
            and isinstance(getattr(seg, "ref", None), dict)
            and seg.ref.get("kind") == "workflow"
            and seg.ref.get("id") == "wf.child"
        ]
        assert len(segs) == 1, f"expected exactly one wf.child segment in path; got {segs!r}"
        child_workflow_instance_ids.append(segs[0].id)

    assert set(branches) == {"p1:0", "p1:1"}
    assert len(set(child_workflow_instance_ids)) == 2
