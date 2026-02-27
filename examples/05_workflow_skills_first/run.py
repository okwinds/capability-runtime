from __future__ import annotations

"""
05_workflow_skills_first：Workflow 编排 skills-first Agent（离线可回归）。

运行：
  python examples/05_workflow_skills_first/run.py --workspace-root /tmp/asr-ex-05
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict

from skills_runtime.llm.chat_sse import ChatStreamEvent
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall
from skills_runtime.safety.approvals import ApprovalDecision, ApprovalProvider, ApprovalRequest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agently_skills_runtime import (  # noqa: E402
    AgentSpec,
    CapabilityKind,
    CapabilityRef,
    CapabilitySpec,
    ExecutionContext,
    InputMapping,
    Runtime,
    RuntimeConfig,
    Step,
    WorkflowSpec,
)


def _detect_skills_space_schema() -> str:
    """
    探测当前安装的 skills-runtime-sdk 期望的 skills.spaces schema。

    返回：
    - "namespace"：上游要求 `skills.spaces[].namespace`
    - "account_domain"：上游要求 `skills.spaces[].account` + `domain`
    """

    try:
        import skills_runtime.config.loader as loader

        space = getattr(getattr(loader, "AgentSdkSkillsConfig", None), "Space", None)
        if space is not None:
            fields = getattr(space, "model_fields", None)
            if isinstance(fields, dict) and "namespace" in fields:
                return "namespace"
    except Exception:
        return "account_domain"

    try:
        import skills_runtime.skills.mentions as mentions

        if hasattr(mentions, "is_valid_namespace"):
            return "namespace"
    except Exception:
        return "account_domain"

    return "account_domain"


class _ApproveAll(ApprovalProvider):
    """离线示例用审批器：永远批准（避免阻塞）。"""

    async def request_approval(self, *, request: ApprovalRequest, timeout_ms: int | None = None) -> ApprovalDecision:
        _ = (request, timeout_ms)
        return ApprovalDecision.APPROVED_FOR_SESSION


def _write_overlay_and_skills(*, workspace_root: Path) -> tuple[Path, Path]:
    """
    写入最小 overlay + skills bundle（filesystem source）。

    参数：
    - workspace_root：工作区根目录

    返回：
    - (overlay_path, skills_root)
    """

    skills_root = workspace_root / "skills"
    (skills_root / "writer").mkdir(parents=True, exist_ok=True)
    (skills_root / "reviewer").mkdir(parents=True, exist_ok=True)
    (skills_root / "writer" / "SKILL.md").write_text(
        "\n".join(["---", "name: writer", 'description: \"demo writer\"', "---", "", "# Writer", ""]) + "\n",
        encoding="utf-8",
    )
    (skills_root / "reviewer" / "SKILL.md").write_text(
        "\n".join(["---", "name: reviewer", 'description: \"demo reviewer\"', "---", "", "# Reviewer", ""]) + "\n",
        encoding="utf-8",
    )

    overlay = workspace_root / "runtime.yaml"
    space_schema = _detect_skills_space_schema()
    lines = [
        "run:",
        "  max_steps: 30",
        "safety:",
        '  mode: \"ask\"',
        "  approval_timeout_ms: 60000",
        "sandbox:",
        "  default_policy: none",
        "skills:",
        "  strictness:",
        "    unknown_mention: error",
        "    duplicate_name: error",
        "    mention_format: strict",
    ]
    if space_schema == "namespace":
        lines.extend(
            [
                "  spaces:",
                "    - id: ex-space",
                '      namespace: \"examples:workflow:skills-first\"',
                "      sources: [ex-fs]",
                "      enabled: true",
            ]
        )
    else:
        lines.extend(
            [
                "  spaces:",
                "    - id: ex-space",
                "      account: examples",
                "      domain: workflow",
                "      sources: [ex-fs]",
                "      enabled: true",
            ]
        )
    lines.extend(
        [
            "  sources:",
            "    - id: ex-fs",
            "      type: filesystem",
            "      options:",
            f"        root: {str(skills_root.resolve())!r}",
        ]
    )
    overlay.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return overlay, skills_root


def _build_backend() -> FakeChatBackend:
    """离线 Fake backend：两次 Agent 调用分别输出 draft / review。"""

    return FakeChatBackend(
        calls=[
            FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="draft"), ChatStreamEvent(type="completed")]),
            FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="review"), ChatStreamEvent(type="completed")]),
        ]
    )


async def _run(*, workspace_root: Path) -> None:
    """构造并运行一个编排 skills-first Agent 的 Workflow。"""

    overlay_path, _skills_root = _write_overlay_and_skills(workspace_root=workspace_root)

    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=workspace_root,
            sdk_config_paths=[overlay_path],
            preflight_mode="off",
            sdk_backend=_build_backend(),
            approval_provider=_ApproveAll(),
        )
    )

    rt.register_many(
        [
            AgentSpec(
                base=CapabilitySpec(
                    id="agent.draft",
                    kind=CapabilityKind.AGENT,
                    name="Draft",
                    description="产出 draft 文本。",
                ),
                skills=["writer"],
            ),
            AgentSpec(
                base=CapabilitySpec(
                    id="agent.review",
                    kind=CapabilityKind.AGENT,
                    name="Review",
                    description="产出 review 文本。",
                ),
                skills=["reviewer"],
            ),
        ]
    )

    wf = WorkflowSpec(
        base=CapabilitySpec(id="wf.skills_first", kind=CapabilityKind.WORKFLOW, name="SkillsFirstWorkflow"),
        steps=[
            Step(id="draft", capability=CapabilityRef(id="agent.draft")),
            Step(id="review", capability=CapabilityRef(id="agent.review")),
        ],
        output_mappings=[
            InputMapping(source="step.draft", target_field="draft"),
            InputMapping(source="step.review", target_field="review"),
        ],
    )
    rt.register(wf)
    assert rt.validate() == []

    ctx = ExecutionContext(run_id="ex_05_workflow_skills_first", max_depth=10, guards=None, bag={})
    res = await rt.run("wf.skills_first", input={}, context=ctx)
    print("=== 05_workflow_skills_first ===")
    print(f"status={res.status.value}")
    print(f"output={json.dumps(res.output, ensure_ascii=False)}")

    # 证据链：Workflow 的 step_results 中携带每步 NodeReport（控制面证据）。
    for step_id, step_result in ctx.step_results.items():
        report = step_result.get("report")
        if report is None:
            continue
        events_path = getattr(report, "events_path", None)
        print(f"step_report[{step_id}].events_path={events_path!r}")

    print("EXAMPLE_OK: examples/05_workflow_skills_first")


def main() -> int:
    parser = argparse.ArgumentParser(description="examples 05_workflow_skills_first")
    parser.add_argument("--workspace-root", default=".", help="Workspace root path")
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root).expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    asyncio.run(_run(workspace_root=workspace_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
