from __future__ import annotations

from pathlib import Path

from capability_runtime import Runtime, RuntimeConfig, RuntimeServices


def _accept_runtime_services(services: RuntimeServices) -> RuntimeServices:
    """类型契约探针：入参必须满足 RuntimeServices Protocol。"""

    return services


def test_runtime_satisfies_runtime_services_protocol() -> None:
    """验证 Runtime 在运行时与类型层面都满足 RuntimeServices 协议。"""

    runtime = Runtime(RuntimeConfig(mode="mock", workspace_root=Path(".")))
    typed = _accept_runtime_services(runtime)
    assert typed is runtime
    assert isinstance(runtime, RuntimeServices)
