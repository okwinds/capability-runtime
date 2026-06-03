from __future__ import annotations

from pathlib import Path


def _read_repo_file(relative_path: str) -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / relative_path).read_text(encoding="utf-8")


def test_review_followups_modules_define_minimal_all_exports() -> None:
    import capability_runtime.config as config_mod
    import capability_runtime.guards as guards_mod
    import capability_runtime.manifest as manifest_mod
    import capability_runtime.runtime as runtime_mod
    import capability_runtime.sdk_lifecycle as sdk_lifecycle_mod
    import capability_runtime.service_facade as service_facade_mod

    assert config_mod.__all__ == [
        "PreflightMode",
        "RuntimeMode",
        "OutputValidationMode",
        "ProviderRequesterStrategy",
        "AgentlyRequesterStrategy",
        "ToolChoiceAfterToolResult",
        "ProviderRequester",
        "ProviderRequesterFactory",
        "CustomTool",
        "RuntimeConfig",
        "normalize_workspace_root",
    ]
    assert runtime_mod.__all__ == ["Runtime"]
    assert sdk_lifecycle_mod.__all__ == ["SdkLifecycle"]
    assert service_facade_mod.__all__ == [
        "RuntimeSession",
        "RuntimeServiceRequest",
        "RuntimeServiceHandle",
        "RuntimeServiceFacade",
        "build_session_context",
    ]
    assert guards_mod.__all__ == ["LoopBreakerError", "ExecutionGuards"]
    assert manifest_mod.__all__ == [
        "CapabilityVisibility",
        "CapabilityManifestEntry",
        "CapabilityDescriptor",
        "build_manifest_entry_from_spec",
        "collect_capability_dependencies",
        "validate_manifest_entry_matches_spec",
    ]


def test_review_followups_agently_backend_uses_shared_usage_helper() -> None:
    source = _read_repo_file("src/capability_runtime/adapters/agently_backend.py")

    assert "from ..utils.usage import _usage_int" in source
    assert "def _usage_int(" not in source


def test_review_followups_runtime_ui_events_mixin_drops_attr_defined_ignores() -> None:
    source = _read_repo_file("src/capability_runtime/runtime_ui_events_mixin.py")

    assert "type: ignore[attr-defined]" not in source


def test_public_config_and_protocol_do_not_import_upstream_sdk_types() -> None:
    """public config/protocol 层应保持 runtime-owned duck-typed contract。"""

    config_source = _read_repo_file("src/capability_runtime/config.py")
    chat_protocol_source = _read_repo_file("src/capability_runtime/protocol/chat_backend.py")

    assert "from skills_runtime" not in config_source
    assert "import skills_runtime" not in config_source
    assert "from skills_runtime" not in chat_protocol_source
    assert "import skills_runtime" not in chat_protocol_source


def test_bridge_examples_prefer_provider_requester_factory() -> None:
    """主示例应展示中立 bridge 注入入口，而不是 legacy provider-native agent 字段。"""

    for rel_path in [
        "examples/01_quickstart/run_bridge.py",
        "examples/03_bridge_e2e/run.py",
        "examples/06_responses_bridge/run.py",
        "examples/10_runtime_bridge_showcase/server.py",
        "examples/apps/_shared/app_support.py",
    ]:
        source = _read_repo_file(rel_path)
        assert "provider_requester_factory=" in source
        assert "agently_agent=" not in source


def test_user_facing_bridge_examples_do_not_top_level_import_upstream_sdk_types() -> None:
    """公开示例不应把上游 SDK 类型作为下游首选接入面。"""

    for rel_path in [
        "examples/03_bridge_e2e/run.py",
        "examples/apps/_shared/app_support.py",
    ]:
        source = _read_repo_file(rel_path)
        top_level_imports = "\n".join(
            line for line in source.splitlines() if line.startswith(("from skills_runtime", "import skills_runtime"))
        )
        assert top_level_imports == ""


def test_live_showcase_only_sets_effective_agent_llm_config_fields() -> None:
    """live showcase 不能展示当前 runtime 不会透传的 LLM 控制字段。"""

    source = _read_repo_file("examples/10_runtime_bridge_showcase/server.py")

    assert '"temperature"' not in source
    assert '"max_tokens"' not in source


def test_env_examples_do_not_use_placeholder_default_model_names() -> None:
    """真实 provider 模板不能继续把 gpt-4 类占位模型当默认 evidence。"""

    root = Path(__file__).resolve().parents[1]
    env_examples = list((root / "examples").rglob(".env.example"))
    assert env_examples
    for path in env_examples:
        source = path.read_text(encoding="utf-8")
        assert 'MODEL_NAME="gpt-4"' not in source
        assert 'MODEL_NAME="gpt-4o-mini"' not in source
        assert "MODEL_NAME=gpt-4o-mini" not in source


def test_real_mode_bootstrap_does_not_default_to_placeholder_model_names() -> None:
    """真实模式 bootstrap 必须显式读取 MODEL_NAME，不得默认 gpt-4 类模型。"""

    for rel_path in [
        "examples/apps/_shared/app_support.py",
        "examples/apps/form_interview_pro/run.py",
        "examples/apps/rules_parser_pro/run.py",
        "examples/apps/incident_triage_assistant/run.py",
        "examples/apps/sse_gateway_minimal/run.py",
        "examples/apps/ci_failure_triage_and_fix/run.py",
    ]:
        source = _read_repo_file(rel_path)
        assert 'env_or_default("MODEL_NAME", "gpt-4o-mini")' not in source
        assert 'env_or_default("MODEL_NAME", "gpt-4")' not in source


def test_real_bridge_examples_set_agent_spec_llm_model() -> None:
    """真实 provider 示例必须把请求模型写入 AgentSpec.llm_config.model。"""

    for rel_path in [
        "examples/01_quickstart/run_bridge.py",
        "examples/03_bridge_e2e/run.py",
        "examples/06_responses_bridge/run.py",
        "examples/10_runtime_bridge_showcase/server.py",
    ]:
        source = _read_repo_file(rel_path)
        assert 'llm_config={"model": os.environ["MODEL_NAME"]' in source


def test_real_provider_smoke_uses_public_openai_provider_helper() -> None:
    """真实 provider release smoke 必须验证公开推荐的 bootstrap helper 路径。"""

    source = _read_repo_file("tests/integration/test_runtime_real_provider_bridge.py")

    assert "build_openai_provider_requester_factory" in source
    assert "provider_requester_factory=" in source
    assert "agently_agent=" not in source


def test_user_facing_docs_do_not_recommend_adapter_internal_provider_agent_helper() -> None:
    """用户文档不能推荐未进入根包 public API 的 provider-native adapter helper。"""

    for rel_path in [
        "help/02-config-reference.md",
        "help/02-config-reference.zh-CN.md",
        "config/README.md",
        "config/README.zh-CN.md",
    ]:
        source = _read_repo_file(rel_path)
        assert "build_provider_requester_factory(provider_agent=" not in source
        assert "adapter-internal" in source or "adapter 内部" in source


def test_live_showcase_returns_provider_transport_evidence() -> None:
    """live showcase 的真实输出必须展示 bridge lane evidence。"""

    source = _read_repo_file("examples/10_runtime_bridge_showcase/server.py")

    assert '"provider_transport": getattr(usage, "provider_transport", None)' in source


def test_live_showcase_does_not_return_raw_exception_text_to_browser() -> None:
    """live showcase 失败响应只能暴露稳定脱敏错误摘要。"""

    source = _read_repo_file("examples/10_runtime_bridge_showcase/server.py")

    assert 'f"{type(exc).__name__}: {exc}"' not in source
    assert '"error_code": "LIVE_PROVIDER_ERROR"' in source


def test_user_facing_docs_do_not_pin_private_showcase_host() -> None:
    """公开示例文档不能写死开发机私有地址。"""

    for rel_path in [
        "examples/README.md",
        "examples/README.zh-CN.md",
        "examples/10_runtime_bridge_showcase/README.md",
        "examples/10_runtime_bridge_showcase/README.zh-CN.md",
    ]:
        assert "100.66.215.80" not in _read_repo_file(rel_path)


def test_user_facing_docs_do_not_claim_runtime_continue_api() -> None:
    """公开文档不能把未交付的 continue/describe_wait API 写成稳定宿主面。"""

    forbidden_snippets = [
        "run / stream / continue",
        "Host wait/resume surface",
        "stable host-facing objects for wait/resume",
        "面向宿主的 wait/resume",
        "wait/resume 与人工审批流程的稳定宿主对象",
    ]
    for rel_path in [
        "README.md",
        "README.zh-CN.md",
        "help/05-hosted-runtime-and-evidence.md",
        "help/05-hosted-runtime-and-evidence.zh-CN.md",
        "docs_for_coding_agent/capability-coverage-map.md",
        "docs_for_coding_agent/capability-coverage-map.zh-CN.md",
    ]:
        source = _read_repo_file(rel_path)
        for snippet in forbidden_snippets:
            assert snippet not in source


def test_showcase_uses_runtime_recall_backend_naming() -> None:
    """showcase 不应继续把 recall preview 命名为 Workspace-owned contract。"""

    source = _read_repo_file("examples/10_runtime_bridge_showcase/index.html")

    assert "raw_workspace_is_wal" not in source
    assert "raw_recall_backend_is_wal=false" in source


def test_recall_preview_diagnostics_are_runtime_owned() -> None:
    """Recall preview public diagnostics 不应继续写出 Workspace-branded codes。"""

    source = _read_repo_file("src/capability_runtime/adapters/agently_workspace.py")
    context_source = _read_repo_file("src/capability_runtime/context_pack.py")

    assert "adapters.agently_workspace" not in context_source
    assert "from ..context_pack import" in source
    assert "WORKSPACE_BACKEND_UNAVAILABLE" not in source
    assert "WORKSPACE_BUILD_CONTEXT_FAILED" not in source
    assert "RECALL_BACKEND_UNAVAILABLE" in context_source
    assert "RECALL_BUILD_CONTEXT_FAILED" in context_source


def test_real_provider_private_http_opt_in_is_documented() -> None:
    """私有 http provider 例外必须是公开可发现的配置，而不是隐藏 env contract。"""

    for rel_path in [
        ".env.example",
        "examples/01_quickstart/.env.example",
        "help/02-config-reference.md",
        "help/02-config-reference.zh-CN.md",
        "config/README.md",
        "config/README.zh-CN.md",
    ]:
        source = _read_repo_file(rel_path)
        assert "CAPRT_REAL_PROVIDER_ALLOW_INSECURE_TRANSPORT" in source
    helper_source = _read_repo_file("src/capability_runtime/adapters/agently_backend.py")
    assert "allow_insecure_transport" in helper_source


def test_dynamic_dag_example_no_longer_has_unintegrated_preview_skip() -> None:
    """Dynamic DAG 示例应展示已集成能力，不能保留建设期 skip 文案。"""

    source = _read_repo_file("examples/05_dynamic_dag_preview/run.py")

    assert "preview_api=unavailable" not in source
    assert "has not been integrated" not in source
    assert "hasattr(runtime" not in source


def test_source_specs_mark_continue_and_intervention_as_preview() -> None:
    """源规格必须和当前 public API 对齐，不能把未交付 continue 写成已完成。"""

    upgrade = _read_repo_file("docs/specs/upgrade-agently-4.1.3.1.md")
    hitl = _read_repo_file("docs/specs/host-hitl-wait-resume-approval-v1.md")
    workflow = _read_repo_file("docs/specs/workflow-host-runtime-state-v1.md")

    assert "代码基线已升级到 `agently==4.1.3.1`" in upgrade
    assert "本轮不提供 `Runtime.continue_run()` / `Runtime.describe_wait()`" in upgrade
    assert "`src/capability_runtime/context_pack.py`" in upgrade
    assert "legacy_action_artifact_refs` 仅作为" in upgrade
    assert "Current Delivery Status" in hitl
    assert "当前版本尚未交付" in hitl
    assert "Current Delivery Status" in workflow
    assert "完整可恢复" in workflow
    assert "pyproject.toml` 当前 pin：`agently==4.0.8" not in upgrade
