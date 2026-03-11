from __future__ import annotations


def test_upstream_agent_sdk_skills_config_has_bundles_defaults() -> None:
    """
    升级护栏（skills-runtime-sdk==0.1.9）：
    - 上游在 `AgentSdkSkillsConfig` 中引入 `bundles`（Phase3 bundles 的预算与缓存策略）；
    - 本仓作为 bridge/adapter 需要“感知但不绑定实现”，至少应确保运行环境确实安装了带该字段的版本，
      否则后续对 Phase3 行为/证据链的假设会漂移。
    """

    from skills_runtime.config.loader import AgentSdkSkillsConfig

    fields = getattr(AgentSdkSkillsConfig, "model_fields", None)
    assert isinstance(fields, dict)
    assert "bundles" in fields

    cfg = AgentSdkSkillsConfig()
    bundles = getattr(cfg, "bundles", None)
    assert bundles is not None

    max_bytes = getattr(bundles, "max_bytes", None)
    cache_dir = getattr(bundles, "cache_dir", None)
    assert isinstance(max_bytes, int)
    assert max_bytes >= 1
    assert isinstance(cache_dir, str)
    assert cache_dir.strip()


def test_upstream_skills_manager_exposes_bundle_root_for_tool_api() -> None:
    """
    升级护栏（skills-runtime-sdk==0.1.9）：
    - Phase3 工具（actions/references）需要从 SkillsManager 获取 bundle_root（filesystem 或 bundle-backed）。
    - 本仓不直接依赖 Redis bundles，但应确保上游该扩展点存在，避免未来适配时“版本漂移未被及时发现”。
    """

    from skills_runtime.skills.manager import SkillsManager

    assert hasattr(SkillsManager, "get_bundle_root_for_tool")
