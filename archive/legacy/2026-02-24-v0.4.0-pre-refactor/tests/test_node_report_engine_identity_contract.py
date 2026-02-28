from __future__ import annotations

from pathlib import Path

import pytest

from agent_sdk.core.errors import FrameworkIssue

import capability_runtime.bridge as runtime_mod
from capability_runtime.bridge import Runtime, RuntimeConfig


class _FakeRequester:
    def generate_request_data(self):
        return type(
            "Req",
            (),
            {
                "data": {"messages": []},
                "request_options": {},
                "stream": True,
                "headers": {},
                "client_options": {},
                "request_url": "x",
            },
        )()

    async def request_model(self, request_data):
        yield ("message", "[DONE]")


def _patch_requester_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 Agently requester factory patch 为离线假实现（避免触网与真实 key）。"""

    def fake_build(*, agently_agent):
        _ = agently_agent
        return lambda: _FakeRequester()

    monkeypatch.setattr(runtime_mod, "build_openai_compatible_requester_factory", fake_build)


def _mk_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    preflight_mode: str = "off",
    upstream_verification_mode: str = "off",
) -> Runtime:
    """构造一个离线可跑的桥接 runtime（必要依赖均通过 monkeypatch 断开）。"""

    _patch_requester_factory(monkeypatch)
    cfg = RuntimeConfig(
        workspace_root=Path("."),
        config_paths=[],
        preflight_mode=preflight_mode,  # type: ignore[arg-type]
        upstream_verification_mode=upstream_verification_mode,  # type: ignore[arg-type]
    )
    return Runtime(agently_agent=object(), config=cfg)


@pytest.mark.asyncio
async def test_engine_name_is_fixed_when_preflight_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    契约护栏：无论 Bridge 走哪条 fail-closed 分支，NodeReport.engine.name 必须稳定。

    本用例覆盖：preflight gate fail-closed（run_async 在执行引擎前返回）。
    """

    rt = _mk_runtime(monkeypatch, preflight_mode="error", upstream_verification_mode="off")
    monkeypatch.setattr(
        rt,
        "preflight",
        lambda: [FrameworkIssue(code="SKILL_PREFLIGHT_FAILED", message="x", details={})],
    )

    out = await rt.run_async("hi")
    assert out.node_report.engine.get("name") == "skills-runtime-sdk-python"
    assert out.node_report.engine.get("module") == "agent_sdk"


@pytest.mark.asyncio
async def test_engine_name_is_fixed_when_upstream_verification_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    契约护栏：upstream strict gate fail-closed 时 engine.name 也必须稳定。
    """

    rt = _mk_runtime(monkeypatch, preflight_mode="off", upstream_verification_mode="strict")
    monkeypatch.setattr(
        rt,
        "verify_upstreams",
        lambda: [FrameworkIssue(code="UPSTREAM_NOT_FROM_EXPECTED_FORK", message="x", details={"module": "agently"})],
    )

    out = await rt.run_async("hi")
    assert out.node_report.engine.get("name") == "skills-runtime-sdk-python"
    assert out.node_report.engine.get("module") == "agent_sdk"

