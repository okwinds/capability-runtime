"""
离线单测：host_toolkit.invoke_capability（公共 API）契约与最小披露。

说明：
- 本用例不依赖真实 LLM / 外网；
- 仅断言工具规格与返回 data 的结构约束（可回归、可审计）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from skills_runtime.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall
from skills_runtime.safety.approvals import ApprovalDecision, ApprovalProvider, ApprovalRequest

from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec, ExecutionContext, Runtime, RuntimeConfig


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
    from capability_runtime.host_toolkit.invoke_capability import (  # type: ignore
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

    ctx = ExecutionContext(run_id="t_invoke_capability_tool", max_depth=5, guards=None)
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
    raw = p.read_bytes()
    assert ic.data.get("artifact_bytes") == len(raw)
    assert ic.data.get("artifact_sha256") == hashlib.sha256(raw).hexdigest()
    obj = json.loads(p.read_text(encoding="utf-8"))
    assert obj.get("schema") == "capability-runtime.invoke_capability.v1"
    assert "child_output_sha256" in obj
    assert "child_output" not in obj, "最小披露：artifact 不应包含 child 输出明文"
    assert "child_output" not in (ic.data or {}), "最小披露：tool data 不应包含 child 输出明文"


def test_invoke_capability_tool_allowlist_rejects_capability_id(tmp_path: Path) -> None:
    outer_backend = FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            LlmToolCall(
                                call_id="ic_perm",
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

    from capability_runtime.host_toolkit.invoke_capability import InvokeCapabilityAllowlist, make_invoke_capability_tool

    tool = make_invoke_capability_tool(
        allowlist=InvokeCapabilityAllowlist(allowed_ids=["child.allowed"]),
        child_runtime_config=replace(cfg, mode="mock", sdk_backend=None),
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
    rt.register(AgentSpec(base=CapabilitySpec(id="outer_perm", kind=CapabilityKind.AGENT, name="OuterPerm")))
    assert rt.validate() == []

    result = asyncio.run(rt.run("outer_perm", input={}, context=ExecutionContext(run_id="t_invoke_capability_perm")))
    assert result.node_report is not None

    ic = next((t for t in (result.node_report.tool_calls or []) if t.name == "invoke_capability"), None)
    assert ic is not None
    assert ic.ok is False
    assert ic.error_kind == "permission"
    assert isinstance(ic.data, dict)
    assert ic.data.get("capability_id") == "child.echo"


def test_invoke_capability_tool_invalid_args_returns_validation_error_kind(tmp_path: Path) -> None:
    outer_backend = FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            LlmToolCall(
                                call_id="ic_validation",
                                name="invoke_capability",
                                # capability_id 为空：触发 pydantic min_length=1 校验失败
                                args={"capability_id": "", "input": {}},
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

    from capability_runtime.host_toolkit.invoke_capability import make_invoke_capability_tool

    tool = make_invoke_capability_tool(
        child_runtime_config=replace(cfg, mode="mock", sdk_backend=None),
        child_specs=[],
        requires_approval=True,
    )

    rt = Runtime(replace(cfg, custom_tools=[tool]))
    rt.register(AgentSpec(base=CapabilitySpec(id="outer_validation", kind=CapabilityKind.AGENT, name="OuterValidation")))
    assert rt.validate() == []

    result = asyncio.run(
        rt.run("outer_validation", input={}, context=ExecutionContext(run_id="t_invoke_capability_validation"))
    )
    assert result.node_report is not None

    ic = next((t for t in (result.node_report.tool_calls or []) if t.name == "invoke_capability"), None)
    assert ic is not None
    assert ic.ok is False
    assert ic.error_kind == "validation"


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

    from capability_runtime.host_toolkit.invoke_capability import InvokeCapabilityAllowlist, make_invoke_capability_tool

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

    ctx = ExecutionContext(run_id="t_invoke_capability_timeout", max_depth=5, guards=None)
    result = asyncio.run(rt.run("outer_timeout", input={}, context=ctx))
    assert result.node_report is not None

    ic = next((t for t in (result.node_report.tool_calls or []) if t.name == "invoke_capability"), None)
    assert ic is not None
    assert ic.ok is False
    assert ic.error_kind == "timeout"


def test_invoke_capability_tool_timeout_cancels_child_run(tmp_path: Path) -> None:
    """
    回归护栏：timeout 后必须尝试取消 child run，不能让 child 在后台继续完成副作用。

    说明：
    - 使用 async child handler（协作取消），确保“取消是否发生”可被稳定观察。
    - 当前断言聚焦 runtime-owned child run 是否继续完成，而不是强杀任意同步业务代码。
    """

    outer_backend = FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            LlmToolCall(
                                call_id="ic_timeout_cancel",
                                name="invoke_capability",
                                args={"capability_id": "child.slow.async", "input": {"x": 1}},
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

    completed: list[str] = []

    async def _slow_async_mock_handler(spec: CapabilitySpec, input_dict: dict) -> str:
        _ = (spec, input_dict)
        await asyncio.sleep(0.05)
        completed.append("child-finished")
        return "child"

    from capability_runtime.host_toolkit.invoke_capability import InvokeCapabilityAllowlist, make_invoke_capability_tool

    tool = make_invoke_capability_tool(
        allowlist=InvokeCapabilityAllowlist(allowed_ids=["child.slow.async"]),
        child_runtime_config=replace(cfg, mode="mock", sdk_backend=None, mock_handler=_slow_async_mock_handler),
        child_specs=[
            AgentSpec(
                base=CapabilitySpec(
                    id="child.slow.async",
                    kind=CapabilityKind.AGENT,
                    name="ChildSlowAsync",
                    description="child agent (slow async mock handler)",
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
                id="outer_timeout_cancel",
                kind=CapabilityKind.AGENT,
                name="OuterTimeoutCancel",
                description="call invoke_capability then say ok",
            )
        )
    )
    assert rt.validate() == []

    result = asyncio.run(rt.run("outer_timeout_cancel", input={}, context=ExecutionContext(run_id="t_invoke_capability_timeout_cancel")))
    assert result.node_report is not None

    ic = next((t for t in (result.node_report.tool_calls or []) if t.name == "invoke_capability"), None)
    assert ic is not None
    assert ic.ok is False
    assert ic.error_kind == "timeout"


def test_async_runner_ensure_started_is_singleton_under_concurrent_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    回归护栏：并发调用 ensure_started() 时，只允许启动一个 live runner。

    说明：
    - 通过延迟的 fake thread_main 放大启动窗口；
    - 若 ensure_started 没有原子保护，多个调用方会在 `_loop` 仍未就绪时重复创建线程。
    """

    from capability_runtime.host_toolkit.invoke_capability import _AsyncRunner

    runner = _AsyncRunner()
    started_loops: list[asyncio.AbstractEventLoop] = []
    started_lock = threading.Lock()
    release_runner = threading.Event()

    def _fake_thread_main() -> None:
        loop = asyncio.new_event_loop()
        with started_lock:
            started_loops.append(loop)
        runner._loop = loop
        runner._ready.set()
        release_runner.wait(timeout=1.0)
        runner._loop = None
        loop.close()

    monkeypatch.setattr(runner, "_thread_main", _fake_thread_main)

    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def _worker() -> None:
        try:
            barrier.wait(timeout=1.0)
            runner.ensure_started()
        except BaseException as exc:  # pragma: no cover - 失败时用于收集线程异常
            errors.append(exc)

    threads = [threading.Thread(target=_worker, daemon=True) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=1.0)
    release_runner.set()

    assert not errors
    assert len(started_loops) == 1, f"expected single live runner start, got {len(started_loops)}"


def test_async_runner_shutdown_resets_state_and_allows_restart() -> None:
    """
    回归护栏：runner 必须支持显式 shutdown，并在后续调用时干净重启。
    """

    from capability_runtime.host_toolkit.invoke_capability import _AsyncRunner

    runner = _AsyncRunner()
    runner.ensure_started()
    first_loop = runner._loop
    assert first_loop is not None

    runner.shutdown()
    assert runner._loop is None
    assert runner._thread is None

    runner.ensure_started()
    assert runner._loop is not None
    assert runner._loop is not first_loop
    runner.shutdown()
