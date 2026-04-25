from __future__ import annotations

from importlib import metadata

import pytest
from pydantic import ValidationError

from skills_runtime.config.loader import AgentSdkPromptConfig
from skills_runtime.prompts.manager import PromptManager, PromptTemplates
from skills_runtime.tools.protocol import ToolSpec


def test_skills_runtime_sdk_0_1_12_prompt_schema_is_available() -> None:
    """
    升级护栏：`skills-runtime-sdk==0.1.12` 必须提供 prompt profile 相关 schema。

    - 入参：无（读取当前安装的上游包与配置模型）
    - 返回：无；断言失败表示运行环境或上游 schema 仍停留在旧版本
    """

    assert metadata.version("skills-runtime-sdk") == "0.1.12"

    field_names = set(AgentSdkPromptConfig.model_fields)
    assert {"profile", "skill_injection", "history", "tools"}.issubset(field_names)

    prompt_config = AgentSdkPromptConfig(
        profile="structured_transform",
        skill_injection={"mode": "explicit_only", "render": "summary"},
        history={"mode": "none", "max_messages": 8, "max_chars": 4096},
        tools={"exposure": "explicit_only"},
    )

    assert prompt_config.profile == "structured_transform"
    assert prompt_config.include_skills_list is None
    assert prompt_config.skill_injection.mode == "explicit_only"
    assert prompt_config.skill_injection.render == "summary"
    assert prompt_config.history.mode == "none"
    assert prompt_config.tools.exposure == "explicit_only"


@pytest.mark.parametrize(
    ("field", "payload"),
    [
        ("profile", {"profile": "legacy"}),
        ("skill_injection.mode", {"skill_injection": {"mode": "legacy"}}),
        ("skill_injection.render", {"skill_injection": {"render": "legacy"}}),
        ("history.mode", {"history": {"mode": "legacy"}}),
        ("tools.exposure", {"tools": {"exposure": "legacy"}}),
    ],
)
def test_skills_runtime_sdk_0_1_12_prompt_schema_rejects_invalid_values(
    field: str,
    payload: dict[str, object],
) -> None:
    """
    升级护栏：prompt profile 新枚举必须由上游 schema fail-fast 拒绝非法值。

    - field：被覆盖的 schema 字段名，仅用于让参数化用例可读
    - payload：传入上游 `AgentSdkPromptConfig` 的局部配置
    - 返回：无；未抛 `ValidationError` 即视为 schema 过宽
    """

    assert field
    with pytest.raises(ValidationError):
        AgentSdkPromptConfig(**payload)


def test_prompt_manager_tool_exposure_filters_provider_tools() -> None:
    """
    升级护栏：`PromptManager` 的 tools exposure 必须过滤真正发给 provider 的工具列表。

    - 入参：构造三个上游 `ToolSpec`
    - 返回：无；断言 `none/all/explicit_only` 三种策略的过滤结果
    """

    templates = PromptTemplates(system_text="system: {task}", developer_text="developer: {tools}")
    tools = [
        ToolSpec(name="alpha_tool", description="alpha"),
        ToolSpec(name="beta_tool", description="beta"),
        ToolSpec(name="gamma_tool", description="gamma"),
    ]

    none_manager = PromptManager(templates=templates, tools_exposure="none")
    assert none_manager.filter_tools_for_task(tools, task="use alpha_tool") == []

    all_manager = PromptManager(templates=templates, tools_exposure="all")
    assert [tool.name for tool in all_manager.filter_tools_for_task(tools, task="no explicit tool")] == [
        "alpha_tool",
        "beta_tool",
        "gamma_tool",
    ]

    explicit_manager = PromptManager(templates=templates, tools_exposure="explicit_only")
    assert [
        tool.name
        for tool in explicit_manager.filter_tools_for_task(
            tools,
            task="please use alpha_tool, not alphabet soup",
            user_input="then beta_tool",
        )
    ] == ["alpha_tool", "beta_tool"]
