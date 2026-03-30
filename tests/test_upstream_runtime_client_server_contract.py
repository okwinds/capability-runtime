from __future__ import annotations

from capability_runtime import Runtime, RuntimeConfig


class _FakeRuntimeServer:
    def __init__(self) -> None:
        self.bound_runtime = None

    def bind_runtime(self, runtime: Runtime) -> None:
        self.bound_runtime = runtime


def test_runtime_config_exposes_optional_runtime_client_and_server_defaults() -> None:
    config = RuntimeConfig()

    assert config.runtime_client is None
    assert config.runtime_server is None


def test_runtime_bind_runtime_server_forwards_local_runtime_without_strict_type_checking() -> None:
    server = _FakeRuntimeServer()
    runtime = Runtime(RuntimeConfig(mode="mock", runtime_server=server))

    runtime.bind_runtime_server()

    assert server.bound_runtime is runtime
