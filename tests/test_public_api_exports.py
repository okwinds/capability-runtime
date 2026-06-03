"""公共 API 导出面回归测试（按输入文档 2.7 收敛）。"""
from __future__ import annotations

import inspect


def test_public_api_all_exports_are_stable() -> None:
    """验证 `capability_runtime.__all__` 仅包含重构后允许暴露的公共符号。"""

    import capability_runtime as caprt

    expected = [
        # Runtime
        "Runtime",
        "RuntimeConfig",
        "ProviderRequesterStrategy",
        "AgentlyRequesterStrategy",
        "ToolChoiceAfterToolResult",
        "ProviderRequester",
        "ProviderRequesterFactory",
        "CustomTool",
        "StructuredStreamEvent",
        "RuntimeContextRecordRef",
        "RuntimeRecallBackend",
        "RuntimeRecallContextPack",
        "build_recall_context_pack",
        "write_node_report_summary",
        "build_openai_provider_requester_factory",
        # Reports
        "NodeReport",
        "NodeResult",
        # Host toolkit (selected)
        "InvokeCapabilityAllowlist",
        "make_invoke_capability_tool",
        # Protocol
        "CapabilityKind",
        "CapabilityRef",
        "CapabilitySpec",
        "CapabilityStatus",
        "CapabilityResult",
        "CapabilityManifestEntry",
        "CapabilityDescriptor",
        "CapabilityVisibility",
        "HostRunStatus",
        "ApprovalTicket",
        "ResumeIntent",
        "HostRunSnapshot",
        "WorkflowRunStatus",
        "WorkflowStepSnapshot",
        "WorkflowRunSnapshot",
        "WorkflowReplayRequest",
        "RuntimeSession",
        "RuntimeServiceRequest",
        "RuntimeServiceHandle",
        "RuntimeServiceFacade",
        "AgentSpec",
        "AgentIOSchema",
        "PromptRenderMode",
        "DynamicWorkflowNode",
        "DynamicWorkflowPlan",
        "WorkflowSpec",
        "Step",
        "LoopStep",
        "ParallelStep",
        "ConditionalStep",
        "InputMapping",
        "ExecutionContext",
        # Errors
        "RuntimeFrameworkError",
        "CapabilityNotFoundError",
    ]

    assert caprt.__all__ == expected
    assert set(caprt.__all__) == set(expected)


def test_public_api_does_not_expose_internal_impl_details() -> None:
    """验证不再暴露内部实现类（Registry/Guards/Adapters/旧入口等）。"""

    import capability_runtime as caprt

    legacy_entry = "Agently" + "SkillsRuntime"
    legacy_config = legacy_entry + "Config"

    forbidden = [
        # 内部实现细节
        "CapabilityRegistry",
        "ExecutionGuards",
        "LoopBreakerError",
        "RecursionLimitError",
        "WorkflowStep",
        "RuntimeServices",
        # Adapters（不作为公共 API）
        "AgentAdapter",
        "WorkflowAdapter",
        # 旧入口（历史）
        legacy_entry,
        legacy_config,
        "CapabilityRuntime",
        "BridgeConfigModel",
        "NodeReportBuilder",
    ]
    for name in forbidden:
        assert not hasattr(caprt, name), name


def test_legacy_agently_requester_strategy_import_remains_available() -> None:
    """旧根包导入与 import-star 仍可用；新文档推荐 ProviderRequesterStrategy。"""

    import capability_runtime as caprt

    assert "AgentlyRequesterStrategy" in caprt.__all__
    assert caprt.AgentlyRequesterStrategy == caprt.ProviderRequesterStrategy


def test_openai_provider_requester_factory_uses_transport_model_parameter() -> None:
    """公开 helper 应避免把 transport bootstrap model 伪装成业务请求模型入口。"""

    import capability_runtime as caprt

    signature = inspect.signature(caprt.build_openai_provider_requester_factory)
    assert list(signature.parameters) == [
        "base_url",
        "transport_model",
        "api_key",
        "strategy",
        "allowed_hosts",
        "allow_insecure_transport",
    ]
    assert "model" not in signature.parameters
