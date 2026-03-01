from __future__ import annotations

"""
离线单测：invoke_capability 支持 shared_runtime（复用 Runtime 实例）。

目标：
- shared_runtime 提供时，invoke_capability 子调用应复用该 Runtime（不创建新的 Runtime 实例）。
- 仍保持最小披露：tool result 返回 artifact 指针与摘要，不回显 child 自由文本。
"""

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path

from skills_runtime.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall
from skills_runtime.safety.approvals import ApprovalDecision, ApprovalProvider, ApprovalRequest

from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec, ExecutionContext, Runtime, RuntimeConfig


class _ApproveAll(ApprovalProvider):
    """测试用：永远批准（避免离线示例阻塞）。"""

    async def request_approval(self, *, request: ApprovalRequest, timeout_ms: int | None = None) -> ApprovalDecision:
        _ = (request, timeout_ms)
        return ApprovalDecision.APPROVED_FOR_SESSION


def test_invoke_capability_shared_runtime_executes_child(tmp_path: Path) -> None:
    # Arrange: outer runtime（离线 sdk_native）触发 invoke_capability，然后输出 ok。
    outer_backend = FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            LlmToolCall(
                                call_id="ic_shared",
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

    cfg = RuntimeConfig(
        mode="sdk_native",
        workspace_root=tmp_path,
        sdk_config_paths=[],
        sdk_backend=outer_backend,
        preflight_mode="off",
        approval_provider=_ApproveAll(),
    )

    # shared runtime：mock 模式，提前注册 child.echo。
    def _shared_mock_handler(spec: CapabilitySpec, input_dict: dict, context: ExecutionContext) -> str:
        _ = (spec, input_dict, context)
        return "shared-child"

    shared_rt = Runtime(RuntimeConfig(mode="mock", mock_handler=_shared_mock_handler))
    shared_rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="child.echo",
                kind=CapabilityKind.AGENT,
                name="ChildEcho",
                description="child agent (shared runtime)",
            )
        )
    )

    from capability_runtime.host_toolkit.invoke_capability import InvokeCapabilityAllowlist, make_invoke_capability_tool

    tool = make_invoke_capability_tool(
        allowlist=InvokeCapabilityAllowlist(allowed_ids=["child.echo"]),
        shared_runtime=shared_rt,
        # 关键：child_specs 故意留空；若实现仍创建新 Runtime，这里会找不到 capability 并失败。
        child_specs=[],
        # 仍需提供（接口保持兼容）；shared_runtime 路径不应依赖该 config 创建新 Runtime。
        child_runtime_config=replace(cfg, mode="mock", sdk_backend=None),
        requires_approval=True,
    )

    outer_rt = Runtime(replace(cfg, custom_tools=[tool]))
    outer_rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="outer_shared",
                kind=CapabilityKind.AGENT,
                name="OuterShared",
                description="call invoke_capability(child.echo) then say ok",
            )
        )
    )
    assert outer_rt.validate() == []

    ctx = ExecutionContext(run_id="t_invoke_capability_shared_runtime", max_depth=5, guards=None, bag={})
    result = asyncio.run(outer_rt.run("outer_shared", input={}, context=ctx))
    assert result.node_report is not None

    ic = next((t for t in (result.node_report.tool_calls or []) if t.name == "invoke_capability"), None)
    assert ic is not None
    assert ic.ok is True

    artifact_path = str((ic.data or {}).get("artifact_path") or "")
    assert artifact_path
    obj = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
    assert obj.get("schema") == "capability-runtime.invoke_capability.v1"

    expected_bytes = b"shared-child"
    assert obj.get("child_output_sha256") == hashlib.sha256(expected_bytes).hexdigest()
    assert obj.get("child_output_bytes") == len(expected_bytes)

