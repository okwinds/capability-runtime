from __future__ import annotations

"""真实 provider bridge contract smoke。

默认跳过，避免离线回归环境访问外部/内网 provider。启用条件：
- CAPRT_REAL_PROVIDER_TESTS=1
- OPENAI_API_KEY / OPENAI_BASE_URL / MODEL_NAME 均存在
"""

import os
from pathlib import Path

import pytest

from capability_runtime import AgentSpec, CapabilityKind, CapabilitySpec, Runtime, RuntimeConfig


pytestmark = pytest.mark.integration

ENABLE = os.getenv("CAPRT_REAL_PROVIDER_TESTS") == "1"
REQUIRED = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "MODEL_NAME")
missing = [key for key in REQUIRED if not os.getenv(key)]
RUN_REAL_PROVIDER = ENABLE and not missing
SKIP_REASON = (
    "CAPRT_REAL_PROVIDER_TESTS 未启用，真实 provider bridge 测试默认跳过。"
    if not ENABLE
    else f"缺少真实 provider 配置：{', '.join(missing)}"
)


def _configure_upstream_agent(strategy: str):
    try:
        from agently import Agently  # type: ignore
    except ModuleNotFoundError:
        pytest.skip("未安装 agently，无法运行真实 bridge smoke。")

    settings_name = "OpenAIResponsesCompatible" if strategy == "responses" else "OpenAICompatible"
    Agently.set_settings(
        settings_name,
        {
            "base_url": os.environ["OPENAI_BASE_URL"],
            "model": os.environ["MODEL_NAME"],
            "auth": os.environ["OPENAI_API_KEY"],
        },
    )
    return Agently


async def _run_bridge_smoke(*, tmp_path: Path, strategy: str, marker: str):
    upstream_facade = _configure_upstream_agent(strategy)
    runtime = Runtime(
        RuntimeConfig(
            mode="bridge",
            workspace_root=tmp_path,
            preflight_mode="off",
            agently_agent=upstream_facade.create_agent(),
            requester_strategy=strategy,
        )
    )
    runtime.register(
        AgentSpec(
            base=CapabilitySpec(
                id=f"agent.real_provider.{strategy}",
                kind=CapabilityKind.AGENT,
                name=f"RealProvider{strategy}",
                description=f"Reply exactly: {marker}",
            ),
            llm_config={"model": os.environ["MODEL_NAME"]},
        )
    )
    assert runtime.validate() == []
    return await runtime.run(f"agent.real_provider.{strategy}", input={"prompt": f"Reply exactly: {marker}"})


def _assert_real_provider_result(result, *, marker: str) -> None:
    assert result.node_report is not None
    assert marker in str(result.output)
    usage = result.node_report.usage
    assert usage is not None
    assert usage.request_id
    assert usage.provider
    assert usage.total_tokens is not None or usage.input_tokens is not None or usage.output_tokens is not None
    assert usage.model == os.environ["MODEL_NAME"]
    if os.environ["MODEL_NAME"] != "gpt-4":
        assert usage.model != "gpt-4"


@pytest.mark.asyncio
@pytest.mark.skipif(not RUN_REAL_PROVIDER, reason=SKIP_REASON)
async def test_real_provider_chat_completions_bridge_preserves_usage_model(tmp_path: Path) -> None:
    result = await _run_bridge_smoke(
        tmp_path=tmp_path,
        strategy="chat_completions",
        marker="caprt-runtime-chat_completions-ok",
    )
    _assert_real_provider_result(result, marker="caprt-runtime-chat_completions-ok")


@pytest.mark.asyncio
@pytest.mark.skipif(not RUN_REAL_PROVIDER, reason=SKIP_REASON)
async def test_real_provider_responses_bridge_preserves_usage_model(tmp_path: Path) -> None:
    result = await _run_bridge_smoke(
        tmp_path=tmp_path,
        strategy="responses",
        marker="caprt-runtime-responses-ok",
    )
    _assert_real_provider_result(result, marker="caprt-runtime-responses-ok")
