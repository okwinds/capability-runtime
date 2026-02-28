from __future__ import annotations

from capability_runtime.host_toolkit.evidence_hooks import SystemPromptEvidence, SystemPromptEvidenceHook
from capability_runtime.host_toolkit.system_prompt import SystemPrompt, compute_system_prompt_digest
from capability_runtime.types import NodeReportV2, NodeResultV2


def test_system_prompt_digest_is_minimal_and_does_not_contain_plaintext():
    secret_marker = "SYSTEM_SECRET_DO_NOT_LEAK"
    prompt = SystemPrompt(system_text=f"policy: {secret_marker}", developer_text="dev", policy_id="p1")
    digest = compute_system_prompt_digest(prompt=prompt)

    assert digest.injected is True
    assert digest.sha256
    assert digest.bytes and digest.bytes > 0
    assert digest.policy_id == "p1"

    dumped = digest.model_dump_json()
    assert secret_marker not in dumped


def test_system_prompt_evidence_hook_writes_meta_without_plaintext():
    secret_marker = "SYSTEM_SECRET_DO_NOT_LEAK"
    prompt = SystemPrompt(system_text=f"policy: {secret_marker}", developer_text="dev", policy_id="p1")
    digest = compute_system_prompt_digest(prompt=prompt)

    evidence = SystemPromptEvidence(
        system_prompt_injected=digest.injected,
        system_prompt_sha256=digest.sha256,
        system_prompt_bytes=digest.bytes,
        system_policy_id=digest.policy_id,
    )
    hook = SystemPromptEvidenceHook(evidence=evidence)

    report = NodeReportV2(
        status="success",
        reason=None,
        completion_reason="run_completed",
        engine={"name": "skills-runtime-sdk-python", "module": "agent_sdk", "version": "0"},
        bridge={"name": "capability-runtime", "version": "0"},
        run_id="r1",
        turn_id="t1",
        events_path="wal.jsonl",
        activated_skills=[],
        tool_calls=[],
        artifacts=[],
        meta={},
    )
    node_result = NodeResultV2(final_output="ok", node_report=report, events_path="wal.jsonl", artifacts=[])

    hook.before_return_result({}, node_result)

    meta_json = node_result.node_report.model_dump_json()
    assert "system_prompt_injected" in node_result.node_report.meta
    assert node_result.node_report.meta.get("system_policy_id") == "p1"
    assert secret_marker not in meta_json
