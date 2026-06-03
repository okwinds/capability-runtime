from __future__ import annotations

from pathlib import Path

import yaml


def _publish_steps() -> dict[str, str]:
    workflow = yaml.safe_load(Path(".github/workflows/publish-pypi.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["publish"]["steps"]
    return {str(step.get("name")): str(step.get("run", "")) for step in steps if isinstance(step, dict) and step.get("name")}


def _workflow() -> dict:
    return yaml.safe_load(Path(".github/workflows/publish-pypi.yml").read_text(encoding="utf-8"))


def _workflow_text() -> str:
    return Path(".github/workflows/publish-pypi.yml").read_text(encoding="utf-8")


def test_publish_workflow_dispatch_checks_out_requested_release_tag() -> None:
    """手工发布必须绑定输入 tag 对应提交，不能在当前分支任意提交上发布。"""

    steps = _workflow()["jobs"]["publish"]["steps"]
    checkout = next(step for step in steps if step.get("name") == "Checkout")

    assert checkout["uses"] == "actions/checkout@v5"
    assert checkout["with"]["ref"] == "${{ github.event_name == 'workflow_dispatch' && format('refs/tags/{0}', github.event.inputs.release_tag) || github.ref }}"


def test_publish_workflow_requires_real_provider_bridge_gate() -> None:
    """发布流程必须显式阻断未验证真实 provider bridge 的 release。"""

    workflow = _workflow_text()
    steps = _publish_steps()
    gate = steps["Real provider bridge release gate"]

    assert "tests/integration/test_runtime_real_provider_bridge.py" in workflow
    assert "CAPRT_REAL_PROVIDER_TESTS=1" in workflow
    assert "CAPRT_REAL_PROVIDER_REQUIRE_TRUSTED_HOST" in workflow
    assert '"1"' in workflow
    assert "CAPRT_REAL_PROVIDER_ALLOWED_HOSTS" in workflow
    assert "CAPRT_REAL_PROVIDER_REQUIRE_IDENTITY" in workflow
    assert "CAPRT_REAL_PROVIDER_MODELS_SHA256" in workflow
    assert "CAPRT_REAL_PROVIDER_DISABLE_TRUSTED_HOST_GUARD_FOR_TESTS" in gate
    assert "CAPRT_REAL_PROVIDER_DISABLE_IDENTITY_GUARD_FOR_TESTS" in gate
    assert "Real provider guard disable variables are forbidden" in gate
    assert "real_provider_smoke_override" not in workflow
    assert "OVERRIDE_" not in gate
    assert "override accepted" not in gate
    assert "--junitxml" in gate
    assert "xml.etree.ElementTree" in gate
    assert "failures" in gate
    assert "errors" in gate
    assert "skipped" in gate
    assert "passed" in gate
    assert "required_real_smokes" in gate
    assert "test_real_provider_chat_completions_bridge_preserves_usage_model" in gate
    assert "test_real_provider_responses_bridge_preserves_usage_model" in gate
    assert "test_real_provider_chat_completions_tool_call_and_approval_evidence" in gate
    assert "test_real_provider_responses_tool_call_and_approval_evidence" in gate
    assert "test_real_provider_responses_named_tool_choice_and_approval_evidence" in gate
    assert "examples/apps/${app}/.env" in gate
    assert "CAPRT_TEST_E2E_BRIDGE=1" in gate
    assert "tests/test_examples_real_integration.py::test_real_form_interview_pro_non_interactive" in gate
    assert (
        "tests/test_examples_real_evidence_strict_integration.py::test_real_incident_triage_assistant_evidence_strict"
        in gate
    )
    assert "exit 1" in gate
    assert "exit 1" in workflow
    assert workflow.index("Real provider bridge release gate") < workflow.index("Build sdist and wheel")


def test_publish_workflow_release_regression_guardrails_cover_upgrade_contracts() -> None:
    """发布前回归必须覆盖上游来源、文档、示例与关键 bridge 契约。"""

    guardrails = _publish_steps()["Release regression guardrails"]
    required_tests = {
        "tests/test_integration_agently_requester_smoke.py",
        "tests/test_repo_no_deep_imports_in_user_facing_docs.py",
        "tests/test_review_followups_module_contracts.py",
        "tests/test_examples_smoke.py",
        "tests/adapters/test_agent_adapter.py",
        "tests/test_per_capability_llm_config_model_routing.py",
        "tests/test_agently_backend_replay.py",
        "tests/test_publish_real_provider_gate.py",
        "tests/test_config_glue.py",
        "tests/test_runtime_hooks_and_schema_gate.py",
        "tests/test_runtime_structured_stream.py",
        "tests/test_workflow_host_runtime_surface.py",
        "tests/test_offline_backend_injection_evidence.py",
        "tests/ui_events/test_runtime_ui_events_agent_stream.py",
        "tests/ui_events/test_dynamic_dag_ui_events.py",
    }

    for test_path in sorted(required_tests):
        assert test_path in guardrails
