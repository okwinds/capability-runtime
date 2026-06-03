from __future__ import annotations

"""真实 provider bridge contract smoke。

默认跳过，避免离线回归环境访问外部/内网 provider。启用条件：
- CAPRT_REAL_PROVIDER_TESTS=1
- OPENAI_API_KEY / OPENAI_BASE_URL / MODEL_NAME 均存在
- CAPRT_REAL_PROVIDER_ALLOWED_HOSTS / CAPRT_REAL_PROVIDER_MODELS_SHA256 均存在
"""

import os
import hashlib
import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlparse

import pytest

from skills_runtime.safety.approvals import ApprovalDecision, ApprovalProvider, ApprovalRequest
from skills_runtime.tools.protocol import ToolCall, ToolResult, ToolSpec

from capability_runtime import (
    AgentSpec,
    CapabilityKind,
    CapabilitySpec,
    CustomTool,
    Runtime,
    RuntimeConfig,
    build_openai_provider_requester_factory,
)


pytestmark = pytest.mark.integration

ENABLE = os.getenv("CAPRT_REAL_PROVIDER_TESTS") == "1"
REQUIRED = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "MODEL_NAME",
    "CAPRT_REAL_PROVIDER_ALLOWED_HOSTS",
    "CAPRT_REAL_PROVIDER_MODELS_SHA256",
)
missing = [key for key in REQUIRED if not os.getenv(key)]
RUN_REAL_PROVIDER = ENABLE and not missing
SKIP_REASON = (
    "CAPRT_REAL_PROVIDER_TESTS 未启用，真实 provider bridge 测试默认跳过。"
    if not ENABLE
    else f"缺少真实 provider 配置：{', '.join(missing)}"
)


def test_trusted_provider_host_rejects_http_without_explicit_allow(monkeypatch: pytest.MonkeyPatch) -> None:
    """发布 gate 默认不应把密钥发往明文 HTTP，除非显式声明允许。"""

    monkeypatch.setenv("CAPRT_REAL_PROVIDER_REQUIRE_TRUSTED_HOST", "1")
    monkeypatch.setenv("CAPRT_REAL_PROVIDER_ALLOWED_HOSTS", "provider.internal")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://provider.internal/v1")
    monkeypatch.delenv("CAPRT_REAL_PROVIDER_ALLOW_INSECURE_TRANSPORT", raising=False)

    with pytest.raises(AssertionError, match="https|insecure"):
        _assert_trusted_provider_host()


def test_trusted_provider_host_allows_http_only_with_explicit_allow(monkeypatch: pytest.MonkeyPatch) -> None:
    """内网 HTTP provider 可作为受控例外，但必须显式打开。"""

    monkeypatch.setenv("CAPRT_REAL_PROVIDER_REQUIRE_TRUSTED_HOST", "1")
    monkeypatch.setenv("CAPRT_REAL_PROVIDER_ALLOWED_HOSTS", "provider.internal")
    monkeypatch.setenv("CAPRT_REAL_PROVIDER_ALLOW_INSECURE_TRANSPORT", "1")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://provider.internal/v1")

    _assert_trusted_provider_host()


def test_real_provider_identity_requires_matching_model_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    """发布 gate 的真实 provider 身份证明必须绑定 `/models` 中的目标模型对象。"""

    model_obj = {"id": "model-live", "object": "model", "supported_endpoint_types": ["openai"]}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return json.dumps({"data": [model_obj]}).encode("utf-8")

    monkeypatch.setenv("CAPRT_REAL_PROVIDER_REQUIRE_IDENTITY", "1")
    monkeypatch.setenv("CAPRT_REAL_PROVIDER_MODELS_SHA256", _canonical_model_fingerprint(model_obj))
    monkeypatch.setenv("OPENAI_BASE_URL", "https://provider.internal/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MODEL_NAME", "model-live")
    monkeypatch.setattr(sys.modules[__name__], "urlopen", lambda *_args, **_kwargs: _Response())

    _assert_real_provider_identity()


def test_real_provider_identity_rejects_mismatched_model_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    """模型对象指纹不匹配时必须 fail-closed，避免受信 host 后的模型目录漂移。"""

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return b'{"data":[{"id":"model-live","object":"model","stub":true}]}'

    monkeypatch.setenv("CAPRT_REAL_PROVIDER_REQUIRE_IDENTITY", "1")
    monkeypatch.setenv("CAPRT_REAL_PROVIDER_MODELS_SHA256", "0" * 64)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://provider.internal/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MODEL_NAME", "model-live")
    monkeypatch.setattr(sys.modules[__name__], "urlopen", lambda *_args, **_kwargs: _Response())

    with pytest.raises(AssertionError, match="fingerprint"):
        _assert_real_provider_identity()


def test_real_provider_identity_is_required_by_default_when_suite_is_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """真实 provider suite 默认必须具备模型目录 fingerprint guard。"""

    monkeypatch.setenv("OPENAI_BASE_URL", "https://provider.internal/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MODEL_NAME", "model-live")
    monkeypatch.delenv("CAPRT_REAL_PROVIDER_MODELS_SHA256", raising=False)
    monkeypatch.delenv("CAPRT_REAL_PROVIDER_REQUIRE_IDENTITY", raising=False)

    with pytest.raises(AssertionError, match="CAPRT_REAL_PROVIDER_MODELS_SHA256"):
        _assert_real_provider_identity()


def _assert_trusted_provider_host() -> None:
    """真实 provider gate 默认要求 OPENAI_BASE_URL 命中受信任 host allowlist。"""

    allowed_hosts = {
        item.strip().lower()
        for item in os.getenv("CAPRT_REAL_PROVIDER_ALLOWED_HOSTS", "").split(",")
        if item.strip()
    }
    assert allowed_hosts, "CAPRT_REAL_PROVIDER_ALLOWED_HOSTS is required when trusted host enforcement is enabled"
    parsed = urlparse(os.environ["OPENAI_BASE_URL"])
    scheme = (parsed.scheme or "").lower()
    allow_insecure = os.getenv("CAPRT_REAL_PROVIDER_ALLOW_INSECURE_TRANSPORT") == "1"
    assert scheme == "https" or allow_insecure, (
        "OPENAI_BASE_URL must use https when trusted host enforcement is enabled; "
        "set CAPRT_REAL_PROVIDER_ALLOW_INSECURE_TRANSPORT=1 only for a controlled private provider."
    )
    host = (parsed.hostname or "").lower()
    assert host in allowed_hosts, f"OPENAI_BASE_URL host {host!r} is not in CAPRT_REAL_PROVIDER_ALLOWED_HOSTS"


def _models_url() -> str:
    return os.environ["OPENAI_BASE_URL"].rstrip("/") + "/models"


def _canonical_model_fingerprint(model_obj: dict) -> str:
    payload = json.dumps(model_obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _assert_real_provider_identity() -> None:
    """真实 provider gate 默认要求 `/models` 中目标模型对象匹配预登记指纹。"""

    expected = os.getenv("CAPRT_REAL_PROVIDER_MODELS_SHA256", "").strip().lower()
    assert expected, "CAPRT_REAL_PROVIDER_MODELS_SHA256 is required when provider identity enforcement is enabled"
    request = Request(
        _models_url(),
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        method="GET",
    )
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    models = payload.get("data") if isinstance(payload, dict) else None
    assert isinstance(models, list), "provider /models response must contain a data list"
    target = next((item for item in models if isinstance(item, dict) and item.get("id") == os.environ["MODEL_NAME"]), None)
    assert target is not None, f"MODEL_NAME {os.environ['MODEL_NAME']!r} was not advertised by /models"
    actual = _canonical_model_fingerprint(target)
    assert actual == expected, "provider /models fingerprint does not match CAPRT_REAL_PROVIDER_MODELS_SHA256"


def _build_provider_requester_factory(strategy: str):
    try:
        return build_openai_provider_requester_factory(
            base_url=os.environ["OPENAI_BASE_URL"],
            transport_model=os.environ["MODEL_NAME"],
            api_key=os.environ["OPENAI_API_KEY"],
            strategy=strategy,  # type: ignore[arg-type]
        )
    except ModuleNotFoundError:
        pytest.skip("未安装 agently，无法运行真实 bridge smoke。")


async def _run_bridge_smoke(*, tmp_path: Path, strategy: str, marker: str):
    _assert_trusted_provider_host()
    _assert_real_provider_identity()
    provider_requester_factory = _build_provider_requester_factory(strategy)
    runtime = Runtime(
        RuntimeConfig(
            mode="bridge",
            workspace_root=tmp_path,
            preflight_mode="off",
            provider_requester_factory=provider_requester_factory,
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


class _ApproveAll(ApprovalProvider):
    async def request_approval(self, *, request: ApprovalRequest, timeout_ms: int | None = None) -> ApprovalDecision:
        _ = (request, timeout_ms)
        return ApprovalDecision.APPROVED_FOR_SESSION


def _marker_tool(marker: str) -> CustomTool:
    spec = ToolSpec(
        name="emit_marker",
        description="Return the exact marker requested by the user. Always call this tool before answering.",
        parameters={
            "type": "object",
            "properties": {
                "marker": {
                    "type": "string",
                    "description": "The exact marker to return.",
                }
            },
            "required": ["marker"],
        },
        requires_approval=True,
    )

    def handler(call: ToolCall, ctx: dict) -> ToolResult:
        _ = ctx
        return ToolResult.ok_payload(
            stdout="emit_marker ok",
            data={"marker": str(call.args.get("marker") or marker)},
        )

    return CustomTool(spec=spec, handler=handler, override=True)


async def _run_bridge_tool_approval_smoke(*, tmp_path: Path, strategy: str, marker: str, tool_choice="required"):
    _assert_trusted_provider_host()
    _assert_real_provider_identity()
    provider_requester_factory = _build_provider_requester_factory(strategy)
    runtime = Runtime(
        RuntimeConfig(
            mode="bridge",
            workspace_root=tmp_path,
            preflight_mode="off",
            provider_requester_factory=provider_requester_factory,
            requester_strategy=strategy,
            tool_choice_after_tool_result="none",
            approval_provider=_ApproveAll(),
            custom_tools=[_marker_tool(marker)],
        )
    )
    runtime.register(
        AgentSpec(
            base=CapabilitySpec(
                id=f"agent.real_provider.tool.{strategy}",
                kind=CapabilityKind.AGENT,
                name=f"RealProviderTool{strategy}",
                description=(
                    "Call the emit_marker tool with the exact marker from the user, "
                    "then answer with that marker."
                ),
            ),
            llm_config={
                "model": os.environ["MODEL_NAME"],
                "tool_choice": tool_choice,
            },
        )
    )
    assert runtime.validate() == []
    return await runtime.run(
        f"agent.real_provider.tool.{strategy}",
        input={"prompt": f"Call emit_marker with marker={marker}, then reply with {marker}."},
    )


def _assert_real_provider_result(result, *, marker: str, strategy: str) -> None:
    assert result.node_report is not None
    assert marker in str(result.output)
    usage = result.node_report.usage
    assert usage is not None
    assert usage.request_id
    if usage.provider is not None:
        assert usage.provider not in {"openai", "openai-compatible", "openai-responses"}
    assert usage.total_tokens is not None or usage.input_tokens is not None or usage.output_tokens is not None
    assert usage.model
    assert usage.provider_transport == strategy
    assert usage.model not in {"gpt-4", "gpt-4o-mini", "YOUR_PROVIDER_MODEL"}


def _assert_real_provider_tool_result(result, *, marker: str, strategy: str) -> None:
    _assert_real_provider_result(result, marker=marker, strategy=strategy)
    report = result.node_report
    assert report is not None
    calls = [call for call in (report.tool_calls or []) if call.name == "emit_marker"]
    assert len(calls) == 1, "real provider should produce exactly one emit_marker tool call"
    call = calls[0]
    assert call.requires_approval is True
    assert call.approval_decision in ("approved", "approved_for_session")
    assert call.ok is True
    assert marker in str(result.output)


@pytest.mark.asyncio
@pytest.mark.skipif(not RUN_REAL_PROVIDER, reason=SKIP_REASON)
async def test_real_provider_chat_completions_bridge_preserves_usage_model(tmp_path: Path) -> None:
    result = await _run_bridge_smoke(
        tmp_path=tmp_path,
        strategy="chat_completions",
        marker="caprt-runtime-chat_completions-ok",
    )
    _assert_real_provider_result(result, marker="caprt-runtime-chat_completions-ok", strategy="chat_completions")


@pytest.mark.asyncio
@pytest.mark.skipif(not RUN_REAL_PROVIDER, reason=SKIP_REASON)
async def test_real_provider_responses_bridge_preserves_usage_model(tmp_path: Path) -> None:
    result = await _run_bridge_smoke(
        tmp_path=tmp_path,
        strategy="responses",
        marker="caprt-runtime-responses-ok",
    )
    _assert_real_provider_result(result, marker="caprt-runtime-responses-ok", strategy="responses")


@pytest.mark.asyncio
@pytest.mark.skipif(not RUN_REAL_PROVIDER, reason=SKIP_REASON)
async def test_real_provider_chat_completions_tool_call_and_approval_evidence(tmp_path: Path) -> None:
    result = await _run_bridge_tool_approval_smoke(
        tmp_path=tmp_path,
        strategy="chat_completions",
        marker="caprt-runtime-chat-tool-ok",
    )
    _assert_real_provider_tool_result(result, marker="caprt-runtime-chat-tool-ok", strategy="chat_completions")


@pytest.mark.asyncio
@pytest.mark.skipif(not RUN_REAL_PROVIDER, reason=SKIP_REASON)
async def test_real_provider_responses_tool_call_and_approval_evidence(tmp_path: Path) -> None:
    result = await _run_bridge_tool_approval_smoke(
        tmp_path=tmp_path,
        strategy="responses",
        marker="caprt-runtime-responses-tool-ok",
    )
    _assert_real_provider_tool_result(result, marker="caprt-runtime-responses-tool-ok", strategy="responses")


@pytest.mark.asyncio
@pytest.mark.skipif(not RUN_REAL_PROVIDER, reason=SKIP_REASON)
async def test_real_provider_responses_named_tool_choice_and_approval_evidence(tmp_path: Path) -> None:
    result = await _run_bridge_tool_approval_smoke(
        tmp_path=tmp_path,
        strategy="responses",
        marker="caprt-runtime-responses-named-tool-ok",
        tool_choice={"type": "function", "function": {"name": "emit_marker"}},
    )
    _assert_real_provider_tool_result(result, marker="caprt-runtime-responses-named-tool-ok", strategy="responses")
