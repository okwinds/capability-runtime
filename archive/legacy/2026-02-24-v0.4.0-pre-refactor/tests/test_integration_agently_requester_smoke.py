from __future__ import annotations

import sys
from pathlib import Path

import pytest

from capability_runtime.adapters.agently_backend import build_openai_compatible_requester_factory


@pytest.mark.integration
def test_agently_openai_compatible_requester_generate_request_data_smoke():
    """
    目标：在 dev-ready 的 `-m integration` 集合中验证：
    - 能加载 Agently fork
    - 能构造 OpenAICompatible requester
    - generate_request_data() 能成功产出 request_url/headers/data 的最小结构（不打外网）
    """

    try:
        import agently  # type: ignore
    except ModuleNotFoundError:
        # 尝试复用本地 sibling fork（推荐开发态结构：<Code>/Agently）
        # __file__ = <repo>/tests/<file>.py，因此 repo_root 应为 parents[1]（而不是 parents[2]）。
        repo_root = Path(__file__).resolve().parents[1]
        code_root = repo_root.parent
        local_agently = code_root / "Agently"
        if local_agently.exists():
            sys.path.insert(0, str(local_agently))
        try:
            import agently  # type: ignore  # noqa: F401
        except ModuleNotFoundError:
            pytest.skip(
                "未安装 agently，且未发现本地 sibling fork `../Agently`。"
                "可用：`pip install agently==4.0.8`，或 `pip install -e ../Agently`（把 Agently repo 放到同级目录）。"
            )

    import agently as agently_mod  # type: ignore

    agently_agent = agently_mod.Agently.create_agent("agently-requester-smoke")
    factory = build_openai_compatible_requester_factory(agently_agent=agently_agent)
    requester = factory()

    request_data = requester.generate_request_data()
    assert getattr(request_data, "request_url", "")
    assert isinstance(getattr(request_data, "headers", {}), dict)
    assert isinstance(getattr(request_data, "data", {}), dict)
