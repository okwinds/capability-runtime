from __future__ import annotations

"""
离线回归：通过 RuntimeConfig 注入 SDK ChatBackend（FakeChatBackend），
确保离线也能走真实 skills_runtime.Agent loop 并产出可审计证据链：
- WAL locator（NodeReport.events_path）
- tool_calls + approvals evidence
- activated_skills（skills-first）
"""

import textwrap
from pathlib import Path
from typing import Optional

import pytest

from skills_runtime.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from skills_runtime.llm.fake import FakeChatBackend, FakeChatCall
from skills_runtime.safety.approvals import ApprovalDecision, ApprovalProvider, ApprovalRequest

from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec, Runtime, RuntimeConfig
from capability_runtime.upstream_compat import detect_skills_space_schema


class _ApproveAll(ApprovalProvider):
    """测试用：永远批准（避免离线示例阻塞）。"""

    async def request_approval(self, *, request: ApprovalRequest, timeout_ms: Optional[int] = None) -> ApprovalDecision:
        _ = (request, timeout_ms)
        return ApprovalDecision.APPROVED


@pytest.mark.asyncio
async def test_offline_injected_fake_backend_produces_wal_node_report_tool_evidence_and_skills(tmp_path: Path) -> None:
    """
    验收点：
    - 通过 RuntimeConfig 注入 FakeChatBackend（无需 monkeypatch）
    - 离线也能生成 WAL locator（NodeReport.events_path）
    - NodeReport 能聚合 tool_calls + approvals evidence
    - skills-first：NodeReport.activated_skills 可观测
    """

    # --- skills bundle（filesystem source）---
    skills_root = tmp_path / "skills"
    (skills_root / "demo-skill").mkdir(parents=True, exist_ok=True)
    (skills_root / "demo-skill" / "SKILL.md").write_text(
        textwrap.dedent(
            """\
            ---
            name: demo-skill
            description: "demo skill for offline evidence chain"
            ---

            # Demo Skill
            """
        ),
        encoding="utf-8",
    )

    # --- SDK overlay（skills spaces + safety）---
    space_schema = detect_skills_space_schema()
    overlay = tmp_path / "runtime.yaml"
    lines = [
        "run:",
        "  max_steps: 30",
        "safety:",
        '  mode: "ask"',
        "  approval_timeout_ms: 60000",
        "  tool_allowlist:",
        '    - "read_file"',
        '    - "grep_files"',
        '    - "list_dir"',
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
                "    - id: app-space",
                '      namespace: "examples:app"',
                "      sources: [app-fs]",
                "      enabled: true",
            ]
        )
    else:
        lines.extend(
            [
                "  spaces:",
                "    - id: app-space",
                "      account: examples",
                "      domain: app",
                "      sources: [app-fs]",
                "      enabled: true",
            ]
        )
    lines.extend(
        [
            "  sources:",
            "    - id: app-fs",
            "      type: filesystem",
            "      options:",
            f'        root: "{skills_root.as_posix()}"',
        ]
    )
    overlay.write_text("\n".join(lines) + "\n", encoding="utf-8")

    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Add File: hello.txt",
            "+hello",
            "*** End Patch",
            "",
        ]
    )

    backend = FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            LlmToolCall(call_id="c1", name="apply_patch", args={"input": patch}),
                        ],
                        finish_reason="tool_calls",
                    ),
                    ChatStreamEvent(type="completed", finish_reason="tool_calls"),
                ]
            ),
            FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="done"), ChatStreamEvent(type="completed")]),
        ]
    )

    rt = Runtime(
        RuntimeConfig(
            mode="sdk_native",
            workspace_root=tmp_path,
            sdk_config_paths=[overlay],
            preflight_mode="off",
            sdk_backend=backend,
            approval_provider=_ApproveAll(),
        )
    )
    rt.register(
        AgentSpec(
            base=CapabilitySpec(
                id="agent.offline",
                kind=CapabilityKind.AGENT,
                name="OfflineAgent",
                description="离线模式：必须调用 apply_patch 添加 hello.txt，然后输出 done。",
            ),
            skills=["demo-skill"],
        )
    )
    assert rt.validate() == []

    terminal = await rt.run("agent.offline", input={})
    assert terminal.status.value in {"success", "failed", "pending", "cancelled"}
    assert terminal.node_report is not None
    assert terminal.node_report.events_path is not None
    assert Path(str(terminal.node_report.events_path)).exists()

    # skills-first evidence
    assert "demo-skill" in (terminal.node_report.activated_skills or [])

    # tool + approvals evidence (apply_patch requires approval)
    tools = terminal.node_report.tool_calls or []
    assert any(t.name == "apply_patch" and t.call_id == "c1" for t in tools)
    t0 = next(t for t in tools if t.call_id == "c1")
    assert t0.requires_approval is True
    assert t0.approval_decision in {"approved", "approved_for_session"}
