"""公共 API 导出面回归测试（按输入文档 2.7 收敛）。"""
from __future__ import annotations


def test_public_api_all_exports_are_stable() -> None:
    """验证 `agently_skills_runtime.__all__` 仅包含重构后允许暴露的公共符号。"""

    import agently_skills_runtime as asr

    expected = [
        # Runtime
        "Runtime",
        "RuntimeConfig",
        "CustomTool",
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
        "AgentSpec",
        "AgentIOSchema",
        "WorkflowSpec",
        "Step",
        "LoopStep",
        "ParallelStep",
        "ConditionalStep",
        "InputMapping",
        "ExecutionContext",
        # Errors
        "AgentlySkillsRuntimeError",
        "AdapterNotFoundError",
        "CapabilityNotFoundError",
    ]

    assert asr.__all__ == expected
    assert set(asr.__all__) == set(expected)


def test_public_api_does_not_expose_internal_impl_details() -> None:
    """验证不再暴露内部实现类（Registry/Guards/Adapters/旧入口等）。"""

    import agently_skills_runtime as asr

    forbidden = [
        # 内部实现细节
        "CapabilityRegistry",
        "ExecutionGuards",
        "LoopBreakerError",
        "RecursionLimitError",
        "WorkflowStep",
        # Adapters（不作为公共 API）
        "AgentAdapter",
        "WorkflowAdapter",
        # 旧入口（历史）
        "AgentlySkillsRuntime",
        "AgentlySkillsRuntimeConfig",
        "CapabilityRuntime",
        "BridgeConfigModel",
    ]
    for name in forbidden:
        assert not hasattr(asr, name), name
