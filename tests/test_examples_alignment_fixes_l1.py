from __future__ import annotations

"""
离线回归（L1）：examples 行为级对齐修复护栏。

覆盖点：
- run_stream 的三类 item 分流：AgentEvent / workflow.* dict / terminal CapabilityResult
- examples 文案契约自洽（避免 artifacts 双层路径）
"""

from pathlib import Path

from capability_runtime import (
    AgentSpec,
    CapabilityKind,
    CapabilityRef,
    CapabilitySpec,
    InputMapping,
    LoopStep,
    Runtime,
    RuntimeConfig,
    Step,
    WorkflowSpec,
)


def test_stream_runtime_with_min_ux_handles_workflow_events() -> None:
    """
    回归：examples/apps/_shared/app_support.py 的 helper 声称支持 Agent/Workflow，
    但 workflow 流会 yield dict（workflow.* 轻量事件）。此测试确保不会误判终态/抛异常。
    """

    from examples.apps._shared.app_support import stream_runtime_with_min_ux  # type: ignore

    def handler(spec: AgentSpec, input: dict, context=None):
        _ = (context,)
        if spec.base.id == "agent.items":
            return {"items": [{"name": "a"}, {"name": "b"}]}
        if spec.base.id == "agent.echo":
            return {"name": str(input.get("name") or "")}
        return {"unknown": spec.base.id}

    rt = Runtime(RuntimeConfig(mode="mock", mock_handler=handler))
    rt.register_many(
        [
            AgentSpec(base=CapabilitySpec(id="agent.items", kind=CapabilityKind.AGENT, name="Items")),
            AgentSpec(base=CapabilitySpec(id="agent.echo", kind=CapabilityKind.AGENT, name="Echo")),
        ]
    )

    wf = WorkflowSpec(
        base=CapabilitySpec(id="wf.demo.items", kind=CapabilityKind.WORKFLOW, name="DemoItems"),
        steps=[
            Step(id="items", capability=CapabilityRef(id="agent.items")),
            LoopStep(
                id="echo",
                capability=CapabilityRef(id="agent.echo"),
                iterate_over="step.items.items",
                item_input_mappings=[InputMapping(source="item.name", target_field="name")],
            ),
        ],
        output_mappings=[InputMapping(source="step.echo", target_field="echoed")],
    )
    rt.register(wf)
    assert rt.validate() == []

    output, wal = stream_runtime_with_min_ux(runtime=rt, capability_id="wf.demo.items", input={})
    assert wal is None  # mock 模式不要求 WAL/NodeReport
    assert "echoed" in output


def test_bridge_e2e_instruction_is_consistent_with_tool_contract() -> None:
    """
    回归：examples/03_bridge_e2e 的工具参数约定 `path` 相对 artifacts/，
    指令不应要求写入 artifacts/hello.py（否则易写成 artifacts/artifacts/hello.py）。
    """

    text = Path("examples/03_bridge_e2e/run.py").read_text(encoding="utf-8")
    assert "artifacts/hello.py" not in text
