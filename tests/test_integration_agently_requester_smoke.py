from __future__ import annotations

from pathlib import Path
import importlib.metadata as importlib_metadata

import pytest

from capability_runtime.adapters.agently_backend import (
    build_openai_compatible_requester_factory,
    build_openai_provider_requester_factory,
)


@pytest.mark.integration
def test_agently_4131_installation_is_the_only_truth_source():
    """
    验证实现环境只使用 `agently==4.1.3.1` 安装态，不从 sibling `../Agently` fallback。

    该测试不访问外网；它只固定上游真相源，避免把当前 editable 4.0.8 或本地 4.1.3
    源码误当作目标 4.1.3.1 行为依据。
    """

    try:
        import agently  # type: ignore
    except ModuleNotFoundError as exc:
        raise AssertionError("未安装 agently；请安装目标版本：`python -m pip install agently==4.1.3.1`。") from exc

    installed_version = importlib_metadata.version("agently")
    imported_from = Path(getattr(agently, "__file__", "")).resolve()
    repo_root = Path(__file__).resolve().parents[1]
    sibling_agently = (repo_root.parent / "Agently").resolve()

    assert installed_version == "4.1.3.1"
    assert sibling_agently not in imported_from.parents


@pytest.mark.integration
def test_agently_openai_compatible_requester_generate_request_data_smoke():
    """
    目标：在 dev-ready 的 `-m integration` 集合中验证：
    - 能加载 `agently==4.1.3.1` 安装态
    - 能构造 OpenAICompatible requester
    - generate_request_data() 能成功产出 request_url/headers/data 的最小结构（不打外网）
    """

    try:
        import agently  # type: ignore
    except ModuleNotFoundError as exc:
        raise AssertionError("未安装 agently；请安装目标版本：`python -m pip install agently==4.1.3.1`。") from exc

    import agently as agently_mod  # type: ignore

    assert importlib_metadata.version("agently") == "4.1.3.1"

    agently_agent = agently_mod.Agently.create_agent("agently-requester-smoke")
    factory = build_openai_compatible_requester_factory(agently_agent=agently_agent)
    requester = factory()

    request_data = requester.generate_request_data()
    assert getattr(request_data, "request_url", "")
    assert isinstance(getattr(request_data, "headers", {}), dict)
    assert isinstance(getattr(request_data, "data", {}), dict)


@pytest.mark.integration
def test_public_openai_provider_requester_responses_generate_request_data_smoke():
    """公开中立 helper 也必须能构造 Responses requester data；不访问网络。"""

    assert importlib_metadata.version("agently") == "4.1.3.1"

    factory = build_openai_provider_requester_factory(
        base_url="https://provider.example/v1",
        transport_model="model-smoke",
        api_key="test-key",
        strategy="responses",
    )
    requester = factory()

    request_data = requester.generate_request_data()
    assert getattr(request_data, "request_url", "")
    assert isinstance(getattr(request_data, "headers", {}), dict)
    assert isinstance(getattr(request_data, "data", {}), dict)
