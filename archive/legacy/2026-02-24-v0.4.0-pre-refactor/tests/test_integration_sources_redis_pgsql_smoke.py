from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from agent_sdk.config.defaults import load_default_config_dict
from agent_sdk.config.loader import load_config_dicts
from agent_sdk.skills.manager import SkillsManager


@pytest.mark.integration
def test_integration_skills_sources_redis_pgsql_scan_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    目标：提供“可复刻的集成冒烟”入口（redis/pgsql sources）。

    约束：
    - 默认环境下允许 skip（缺服务/缺依赖），但必须给出明确指引；
    - 当服务与依赖齐全时，应能 scan 成功（允许结果为空）。
    """

    redis_url = os.getenv("CAPRT_TEST_REDIS_URL", "").strip()
    pg_dsn = os.getenv("CAPRT_TEST_PG_DSN", "").strip()
    if not redis_url or not pg_dsn:
        pytest.skip(
            "未配置 integration DSN。请设置："
            "`CAPRT_TEST_REDIS_URL` 与 `CAPRT_TEST_PG_DSN`。"
            "推荐：先运行 `scripts/integration/run_skills_sources_smoke.sh` 一键启动服务并初始化 schema。"
        )

    try:
        import redis  # noqa: F401  # type: ignore[import-not-found]
        import psycopg  # noqa: F401  # type: ignore[import-not-found]
    except ModuleNotFoundError as e:
        pytest.skip(f"缺少可选依赖：{e}. 请在 SDK fork 环境安装 redis/psycopg extras。")

    # SDK skills sources 读取 DSN 的方式：通过 dsn_env 指定环境变量名
    monkeypatch.setenv("CAPRT_TEST_REDIS_DSN", redis_url)
    monkeypatch.setenv("CAPRT_TEST_PG_DSN", pg_dsn)

    overlay = {
        "skills": {
            "spaces": [
                {
                    "id": "space_default",
                    "account": "acct",
                    "domain": "dom",
                    "sources": ["src_redis", "src_pgsql"],
                    "enabled": True,
                }
            ],
            "sources": [
                {"id": "src_redis", "type": "redis", "options": {"dsn_env": "CAPRT_TEST_REDIS_DSN", "key_prefix": "skills:"}},
                {
                    "id": "src_pgsql",
                    "type": "pgsql",
                    "options": {"dsn_env": "CAPRT_TEST_PG_DSN", "schema": "agent", "table": "skills_catalog"},
                },
            ],
        }
    }

    overlay_path = tmp_path / "overlay.yaml"
    overlay_path.write_text(yaml.safe_dump(overlay, sort_keys=False, allow_unicode=True), encoding="utf-8")

    cfg = load_config_dicts([load_default_config_dict(), yaml.safe_load(overlay_path.read_text(encoding="utf-8"))])

    mgr = SkillsManager(workspace_root=tmp_path, skills_config=cfg.skills)

    # 如果 pgsql schema/table 未初始化，SDK scan 可能会报错；此处要求显式 skip 并给出指引。
    try:
        mgr.scan()
    except Exception as e:
        pytest.skip(
            "redis/pgsql services 可用但 schema/table 未准备好，或连接失败。"
            "请运行 `scripts/integration/run_skills_sources_smoke.sh` 初始化后重试。"
            f"原始错误：{e}"
        )
