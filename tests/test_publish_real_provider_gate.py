from __future__ import annotations

from pathlib import Path

import yaml


def _publish_steps() -> dict[str, str]:
    workflow = yaml.safe_load(Path(".github/workflows/publish-pypi.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["publish"]["steps"]
    return {str(step.get("name")): str(step.get("run", "")) for step in steps if isinstance(step, dict) and step.get("name")}


def test_publish_workflow_requires_real_provider_bridge_gate() -> None:
    """发布流程必须显式阻断未验证真实 provider bridge 的 release。"""

    workflow = Path(".github/workflows/publish-pypi.yml").read_text(encoding="utf-8")
    steps = _publish_steps()
    gate = steps["Real provider bridge release gate"]

    assert "tests/integration/test_runtime_real_provider_bridge.py" in workflow
    assert "CAPRT_REAL_PROVIDER_TESTS=1" in workflow
    assert "real_provider_smoke_override_reason" in workflow
    assert "real_provider_smoke_override_url" in workflow
    assert "real_provider_smoke_override_commit" in workflow
    assert "OVERRIDE_URL" in gate
    assert "OVERRIDE_COMMIT" in gate
    assert "GITHUB_REPOSITORY" in gate
    assert "/actions/runs/" in gate
    assert "GITHUB_SHA" in gate
    assert "real provider bridge smoke override accepted" in gate
    assert "OVERRIDE_REASON" not in gate.split("real provider bridge smoke override accepted", 1)[-1]
    assert "--junitxml" in gate
    assert "xml.etree.ElementTree" in gate
    assert "failures" in gate
    assert "errors" in gate
    assert "skipped" in gate
    assert "passed" in gate
    assert "exit 1" in gate
    assert "exit 1" in workflow
    assert workflow.index("Real provider bridge release gate") < workflow.index("Build sdist and wheel")


def test_publish_workflow_release_regression_guardrails_cover_upgrade_contracts() -> None:
    """发布前回归必须覆盖上游来源、文档、示例与关键 bridge 契约。"""

    guardrails = _publish_steps()["Release regression guardrails"]
    required_tests = {
        "tests/test_integration_agently_requester_smoke.py",
        "tests/test_repo_no_deep_imports_in_user_facing_docs.py",
        "tests/test_examples_smoke.py",
        "tests/adapters/test_agent_adapter.py",
        "tests/test_per_capability_llm_config_model_routing.py",
        "tests/test_agently_backend_replay.py",
        "tests/test_publish_real_provider_gate.py",
    }

    for test_path in sorted(required_tests):
        assert test_path in guardrails
