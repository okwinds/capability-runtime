from __future__ import annotations

"""
离线单测：host_toolkit.invoke_capability（公共 API）契约与最小披露。

说明：
- 本用例不依赖真实 LLM / 外网；
- 仅断言工具规格与返回 data 的结构约束（可回归、可审计）。
"""

import asyncio
import json
import time
from dataclasses import replace
from pathlib import Path

from skills_runtime.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall
from skills_runtime.safety.approvals import ApprovalDecision, ApprovalProvider, ApprovalRequest

from agently_skills_runtime import AgentSpec, CapabilityKind, CapabilitySpec, ExecutionContext, Runtime, RuntimeConfig


class _ApproveAll(ApprovalProvider):
    """测试用：永远批准（避免离线示例阻塞）。"""

    async def request_approval(self, *, request: ApprovalRequest, timeout_ms: int | None = None) -> ApprovalDecision:
        _ = (request, timeout_ms)
        return ApprovalDecision.APPROVED_FOR_SESSION


def test_invoke_capability_tool_returns_artifact_digest(tmp_path: Path) -> None:
    # Arrange: outer runtime（离线 sdk_native）触发 invoke_capability，然后输出 ok。
    outer_backend = FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            LlmToolCall(
                                call_id="ic1",
                                name="invoke_capability",
                                args={"capability_id": "child.echo", "input": {"x": 1}},
                            )
                        ],
                        finish_reason="tool_calls",
                    ),
                    ChatStreamEvent(type="completed", finish_reason="tool_calls"),
                ]
            ),
            FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="ok"), ChatStreamEvent(type="completed")]),
        ]
    )

    # Child backend：直接输出（不触发 tools）。
    child_backend = FakeChatBackend(
        calls=[FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="child"), ChatStreamEvent(type="completed")])]
    )

    cfg = RuntimeConfig(
        mode="sdk_native",
        workspace_root=tmp_path,
        sdk_config_paths=[],
        sdk_backend=outer_backend,
        preflight_mode="off",
        approval_provider=_ApproveAll(),
    )

    # 目标：在未实现 invoke_capability 前，该 import/调用会失败，作为 TDD RED。
    from agently_skills_runtime.host_toolkit.invoke_capability import (  # type: ignore
        InvokeCapabilityAllowlist,
        make_invoke_capability_tool,
    )

    tool = make_invoke_capability_tool(
        allowlist=InvokeCapabilityAllowlist(allowed_ids=["child.echo"]),
        child_runtime_config=replace(cfg, sdk_backend=child_backend),
        child_specs=[
            AgentSpec(
                base=CapabilitySpec(
                    id="child.echo",
                    kind=CapabilityKind.AGENT,
                    name="ChildEcho",
                    description="child agent",
                )
            )
        ],
        requires_approval=True,
    )

    rt = Runtime(replace(cfg, custom_tools=[tool]))
    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="outer",
                kind=CapabilityKind.AGENT,
                name="Outer",
                description="call invoke_capability then say ok",
            )
        )
    )
    assert rt.validate() == []

    ctx = ExecutionContext(run_id="t_invoke_capability_tool", max_depth=5, guards=None, bag={})
    result = asyncio.run(rt.run("outer", input={}, context=ctx))
    assert result.node_report is not None

    # Assert: NodeReport 中应存在 invoke_capability tool evidence。
    ic = next((t for t in (result.node_report.tool_calls or []) if t.name == "invoke_capability"), None)
    assert ic is not None
    assert ic.ok is True
    assert isinstance(ic.data, dict)
    assert ic.data.get("child_capability_status") in {"success", "failed", "pending", "cancelled"}

    # 最小披露：必须返回 artifact 指针与摘要，且 data 里不包含 child 的完整自由文本输出。
    artifact_path = str(ic.data.get("artifact_path") or "")
    assert artifact_path
    p = Path(artifact_path)
    assert p.exists()
    obj = json.loads(p.read_text(encoding="utf-8"))
    assert obj.get("schema") == "agently-skills-runtime.invoke_capability.v1"
    assert "child_output_sha256" in obj


def test_invoke_capability_tool_timeout_sets_error_kind(tmp_path: Path) -> None:
    # Arrange: outer runtime 触发 invoke_capability，但 child 在 mock handler 中阻塞，导致超时。
    outer_backend = FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            LlmToolCall(
                                call_id="ic_timeout",
                                name="invoke_capability",
                                args={"capability_id": "child.slow", "input": {"x": 1}},
                            )
                        ],
                        finish_reason="tool_calls",
                    ),
                    ChatStreamEvent(type="completed", finish_reason="tool_calls"),
                ]
            ),
            FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="ok"), ChatStreamEvent(type="completed")]),
        ]
    )

    cfg = RuntimeConfig(
        mode="sdk_native",
        workspace_root=tmp_path,
        sdk_config_paths=[],
        sdk_backend=outer_backend,
        preflight_mode="off",
        approval_provider=_ApproveAll(),
    )

    def _slow_mock_handler(spec: CapabilitySpec, input_dict: dict) -> str:
        _ = (spec, input_dict)
        time.sleep(0.05)
        return "child"

    from agently_skills_runtime.host_toolkit.invoke_capability import InvokeCapabilityAllowlist, make_invoke_capability_tool

    tool = make_invoke_capability_tool(
        allowlist=InvokeCapabilityAllowlist(allowed_ids=["child.slow"]),
        child_runtime_config=replace(cfg, mode="mock", sdk_backend=None, mock_handler=_slow_mock_handler),
        child_specs=[
            AgentSpec(
                base=CapabilitySpec(
                    id="child.slow",
                    kind=CapabilityKind.AGENT,
                    name="ChildSlow",
                    description="child agent (slow mock handler)",
                )
            )
        ],
        requires_approval=True,
        timeout_ms=1,
    )

    rt = Runtime(replace(cfg, custom_tools=[tool]))
    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="outer_timeout",
                kind=CapabilityKind.AGENT,
                name="OuterTimeout",
                description="call invoke_capability then say ok",
            )
        )
    )
    assert rt.validate() == []

    ctx = ExecutionContext(run_id="t_invoke_capability_timeout", max_depth=5, guards=None, bag={})
    result = asyncio.run(rt.run("outer_timeout", input={}, context=ctx))
    assert result.node_report is not None

    ic = next((t for t in (result.node_report.tool_calls or []) if t.name == "invoke_capability"), None)
    assert ic is not None
    assert ic.ok is False
    assert ic.error_kind == "timeout"
