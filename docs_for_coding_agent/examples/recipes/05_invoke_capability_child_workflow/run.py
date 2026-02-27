from __future__ import annotations

"""
Recipe 示例：05_invoke_capability_child_workflow

演示内容：
- outer agent 触发 invoke_capability
- invoke_capability 委托执行子 Workflow（child.wf）
- 子 Workflow 在 mock 模式下运行（确定性输出，便于离线回归）

离线运行：
  python docs_for_coding_agent/examples/recipes/05_invoke_capability_child_workflow/run.py --workspace-root /tmp/asr-recipe-05
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict

from skills_runtime.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SRC_ROOT = _REPO_ROOT / "src"
for p in (str(_REPO_ROOT), str(_SRC_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agently_skills_runtime import (  # noqa: E402
    AgentSpec,
    CapabilityKind,
    CapabilityRef,
    CapabilitySpec,
    ExecutionContext,
    InputMapping,
    RuntimeConfig,
    Step,
    WorkflowSpec,
)
from agently_skills_runtime import InvokeCapabilityAllowlist, make_invoke_capability_tool  # noqa: E402

from docs_for_coding_agent.examples._shared.example_support import (  # noqa: E402
    build_offline_runtime,
    prepare_example_workspace,
)


def _build_outer_backend() -> FakeChatBackend:
    """离线 Fake backend：invoke_capability(child.wf) → 输出 ok。"""

    return FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            LlmToolCall(
                                call_id="ic_wf_1",
                                name="invoke_capability",
                                args={"capability_id": "child.wf", "input": {"name": "alice"}},
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


def _child_mock_handler(spec: AgentSpec, input: Dict[str, Any], context=None) -> Any:
    """
    子 Workflow mock handler：为子 Agent 产出确定性输出。

    参数：
    - spec：子 AgentSpec
    - input：输入 dict
    - context：可选（本例不使用）
    """

    _ = context
    if spec.base.id == "child.agent.hello":
        return {"hello": f"hi {input.get('name', '')}"}
    if spec.base.id == "child.agent.upper":
        return {"upper": str(input.get("name", "")).upper()}
    return {"unknown": spec.base.id}


def main() -> int:
    parser = argparse.ArgumentParser(description="recipe 05_invoke_capability_child_workflow")
    parser.add_argument("--workspace-root", default=".", help="Workspace root path")
    args = parser.parse_args()

    ws = prepare_example_workspace(
        workspace_root=Path(args.workspace_root).expanduser().resolve(),
        skills={
            "delegator": "\n".join(
                [
                    "---",
                    "name: delegator",
                    'description: "demo skill for invoke_capability workflow recipe"',
                    "---",
                    "",
                    "# Delegator",
                    "",
                ]
            )
        },
        safety_mode="ask",
        max_steps=30,
    )

    child_cfg = RuntimeConfig(mode="mock", mock_handler=_child_mock_handler, max_depth=10, max_total_loop_iterations=50000)

    child_wf = WorkflowSpec(
        base=CapabilitySpec(id="child.wf", kind=CapabilityKind.WORKFLOW, name="ChildWorkflow"),
        steps=[
            Step(id="hello", capability=CapabilityRef(id="child.agent.hello"), input_mappings=[InputMapping(source="context.name", target_field="name")]),
            Step(id="upper", capability=CapabilityRef(id="child.agent.upper"), input_mappings=[InputMapping(source="context.name", target_field="name")]),
        ],
        output_mappings=[
            InputMapping(source="step.hello.hello", target_field="hello"),
            InputMapping(source="step.upper.upper", target_field="upper"),
        ],
    )

    invoke_tool = make_invoke_capability_tool(
        child_runtime_config=child_cfg,
        child_specs=[
            AgentSpec(base=CapabilitySpec(id="child.agent.hello", kind=CapabilityKind.AGENT, name="Hello")),
            AgentSpec(base=CapabilitySpec(id="child.agent.upper", kind=CapabilityKind.AGENT, name="Upper")),
            child_wf,
        ],
        allowlist=InvokeCapabilityAllowlist(allowed_ids=["child.wf"]),
        requires_approval=True,
    )

    rt = build_offline_runtime(
        workspace_root=ws.workspace_root,
        overlay_path=ws.overlay_path,
        sdk_backend=_build_outer_backend(),
        preflight_mode="off",
        custom_tools=[invoke_tool],
    )
    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="recipe.invoke_capability.child_workflow",
                kind=CapabilityKind.AGENT,
                name="RecipeInvokeCapabilityChildWorkflow",
                description="必须调用 invoke_capability 执行 child.wf，然后输出 ok。",
            ),
            skills=["delegator"],
        )
    )
    assert rt.validate() == []

    ctx = ExecutionContext(run_id="recipe_05_invoke_capability_child_workflow", max_depth=5, guards=None, bag={})
    result = asyncio.run(rt.run("recipe.invoke_capability.child_workflow", input={}, context=ctx))
    assert result.node_report is not None
    assert result.node_report.events_path is not None
    wal = Path(str(result.node_report.events_path))
    assert wal.exists()

    tools = result.node_report.tool_calls or []
    inv = next((t for t in tools if t.name == "invoke_capability"), None)
    assert inv is not None
    assert inv.ok is True
    assert isinstance(inv.data, dict)
    artifact_path = Path(str(inv.data.get("artifact_path") or ""))
    assert artifact_path.exists()
    obj = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert obj.get("schema") == "agently-skills-runtime.invoke_capability.v1"

    print("EXAMPLE_OK: recipes/05_invoke_capability_child_workflow")
    print(f"wal_locator={result.node_report.events_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
