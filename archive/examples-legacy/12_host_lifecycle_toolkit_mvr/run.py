from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import List, Optional

import yaml

from agent_sdk.core.agent import Agent
from agent_sdk.llm.chat_sse import ChatStreamEvent, ToolCall as LlmToolCall
from agent_sdk.llm.fake import FakeChatBackend, FakeChatCall
from agent_sdk.safety.approvals import ApprovalDecision, ApprovalProvider, ApprovalRequest

from agently_skills_runtime.host_toolkit import (
    ApprovalsProfiles,
    HistoryAssembler,
    StaticSystemPromptProvider,
    SystemPrompt,
    SystemPromptEvidence,
    SystemPromptEvidenceHook,
    TurnDelta,
    validate_approvals_profile,
)
from agently_skills_runtime.host_toolkit.resume import build_resume_replay_summary, load_agent_events_from_jsonl
from agently_skills_runtime.host_toolkit.system_prompt import build_prompt_overlay, compute_system_prompt_digest
from agently_skills_runtime.reporting.node_report import NodeReportBuilder
from agently_skills_runtime.types import NodeResultV2


class _SleepyApprovalProvider(ApprovalProvider):
    """
    示例用 ApprovalProvider：模拟“阻塞等待人类审批”。

    注意：
    - 这里用 sleep 模拟等待；真实生产实现通常是 Web UI/平台审批后唤醒。
    """

    def __init__(self, *, delay_sec: float = 0.2, decision: ApprovalDecision = ApprovalDecision.APPROVED):
        self._delay_sec = delay_sec
        self._decision = decision

    async def request_approval(self, *, request: ApprovalRequest, timeout_ms: Optional[int] = None) -> ApprovalDecision:
        await asyncio.sleep(self._delay_sec)
        return self._decision


def _extract_final_output(events: List) -> str:
    for ev in events:
        if ev.type == "run_completed":
            return str(ev.payload.get("final_output") or "")
        if ev.type in ("run_failed", "run_cancelled"):
            return str(ev.payload.get("message") or "")
    return ""


def main() -> None:
    session_id = "sess_demo"
    host_turn_id = "turn_1"
    run_id = "run_demo_1"

    # 1) system/developer 策略提示词：通过 SDK overlays 注入（MVR）
    provider = StaticSystemPromptProvider(
        prompt=SystemPrompt(
            system_text="你是一个严格遵守安全策略的框架级助手。",
            developer_text="优先输出可审计证据链；不得泄露 secrets。",
            policy_id="policy_demo_v1",
        )
    )
    system_prompt = provider.get_system_prompt(context={"session_id": session_id})
    digest = compute_system_prompt_digest(prompt=system_prompt)
    evidence_hook = SystemPromptEvidenceHook(
        evidence=SystemPromptEvidence(
            system_prompt_injected=digest.injected,
            system_prompt_sha256=digest.sha256,
            system_prompt_bytes=digest.bytes,
            system_policy_id=digest.policy_id,
        )
    )

    # 2) approvals profiles：校验 approval_timeout 与 run wall-time 的关系
    profiles = ApprovalsProfiles()
    validate_approvals_profile(profile=profiles.dev)

    overlay = {}
    overlay.update(build_prompt_overlay(prompt=system_prompt))
    overlay.update(profiles.dev.to_sdk_overlay())

    # 3) 准备一个 offline Agent：Fake backend 触发一次 file_write + approvals
    backend = FakeChatBackend(
        calls=[
            FakeChatCall(
                events=[
                    ChatStreamEvent(
                        type="tool_calls",
                        tool_calls=[
                            LlmToolCall(
                                call_id="c1",
                                name="file_write",
                                args={"path": "hello.txt", "content": "hello from host toolkit example"},
                            )
                        ],
                    )
                ]
            ),
            FakeChatCall(events=[ChatStreamEvent(type="text_delta", text="done"), ChatStreamEvent(type="completed")]),
        ]
    )

    with tempfile.TemporaryDirectory(prefix="host_toolkit_demo_") as td:
        workspace_root = Path(td)
        overlay_path = workspace_root / "overlay.yaml"
        overlay_path.write_text(yaml.safe_dump(overlay, sort_keys=False, allow_unicode=True), encoding="utf-8")

        agent = Agent(
            workspace_root=workspace_root,
            backend=backend,
            approval_provider=_SleepyApprovalProvider(),
            human_io=None,
            env_vars={},
            config_paths=[overlay_path],
        )

        events = list(agent.run_stream("写入一个演示文件，然后返回 done。", run_id=run_id, initial_history=None))

        report = NodeReportBuilder().build(events=events)
        final_output = _extract_final_output(events)
        node_result = NodeResultV2(final_output=final_output, node_report=report, events_path=report.events_path, artifacts=[])

        # 4) 证据链摘要：把 system 注入摘要写入 NodeReport.meta（不落明文）
        evidence_hook.before_return_result({"session_id": session_id, "host_turn_id": host_turn_id}, node_result)

        # 5) Host 真相源：存储 TurnDelta，并用 HistoryAssembler 回传 initial_history
        turn_delta = TurnDelta(
            session_id=session_id,
            host_turn_id=host_turn_id,
            run_id=run_id,
            user_input="写入一个演示文件，然后返回 done。",
            final_output=node_result.final_output,
            node_report=node_result.node_report,
            events_path=node_result.events_path,
        )
        store: List[TurnDelta] = [turn_delta]
        initial_history = HistoryAssembler().build_initial_history(deltas=store)

        print("=== NodeReport.status ===")
        print(report.status, report.reason)
        print("=== NodeReport.meta (excerpt) ===")
        for k in ("system_prompt_injected", "system_prompt_sha256", "system_prompt_bytes", "system_policy_id"):
            print(f"- {k}: {report.meta.get(k)}")
        print("=== initial_history ===")
        print(initial_history)
        print("=== events_path ===")
        print(node_result.events_path)

        # 6) resume helper：从 WAL 回放得到最小 resume state + 摘要（默认用于诊断）
        if node_result.events_path:
            events_path = Path(node_result.events_path)
            loaded = load_agent_events_from_jsonl(events_path=events_path)
            _st, summary = build_resume_replay_summary(events=loaded)
            print("=== resume replay summary ===")
            print(summary.model_dump())

        print(f"workspace_root: {workspace_root}")


if __name__ == "__main__":
    main()

