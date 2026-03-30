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
