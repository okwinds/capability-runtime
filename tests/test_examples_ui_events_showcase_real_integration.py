from __future__ import annotations

"""
UI events showcase 的 real 模式集成冒烟（可选，默认跳过）。

目标：
- 仅在显式门禁开启时验证 /api/start(mode=real) + /api/events 可以跑通并产出 evidence 指针；
- 避免在默认离线回归中触达真实 provider 或产生费用。
"""

import json
import os
from pathlib import Path
from urllib.request import urlopen

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]

# 集成回归依赖上游网络 client（httpx/anyio）。在部分环境下其连接回收会触发
# `PytestUnraisableExceptionWarning`（通常是 Response/connection pool aclose 在无 event loop 时被回收）。
# 该问题属于上游资源回收时序，不影响本测试“real 链路能跑通 + evidence pointer 可得”的验收目标，因此忽略。
pytestmark = pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")


def _env_exists() -> bool:
    return (_REPO_ROOT / "examples/apps/ui_events_showcase/.env").exists()


@pytest.mark.integration
def test_ui_events_showcase_real_mode_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if os.environ.get("CAPRT_TEST_E2E_BRIDGE") != "1":
        pytest.skip("real mode is gated: set CAPRT_TEST_E2E_BRIDGE=1")
    if not _env_exists():
        pytest.skip("missing examples/apps/ui_events_showcase/.env")

    from examples.apps.ui_events_showcase.run import create_server  # type: ignore

    httpd = create_server(host="127.0.0.1", port=0, mode="offline", workspace_root=tmp_path)
    host, port = httpd.server_address[0], int(httpd.server_address[1])

    import threading

    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        # start real session
        with urlopen(f"http://{host}:{port}/api/start?mode=real&level=ui", timeout=30) as resp:
            started = json.loads(resp.read().decode("utf-8"))
        session_id = str(started.get("session_id") or "")
        assert session_id

        # consume a few events, then stop at terminal status if present
        events = []
        with urlopen(
            f"http://{host}:{port}/api/events?session_id={session_id}&transport=jsonl",
            timeout=120,
        ) as resp2:
            for _ in range(200):
                line = resp2.readline()
                if not line:
                    break
                ev = json.loads(line.decode("utf-8"))
                events.append(ev)
                if ev.get("schema") == "capability-runtime.runtime_event.v1" and ev.get("type") == "run.status":
                    st = (ev.get("data") or {}).get("status")
                    if st and st != "running":
                        break

        assert events, "expected at least one real runtime event"
        assert any(e.get("schema") == "capability-runtime.runtime_event.v1" for e in events)

        terminal = None
        for e in reversed(events):
            if e.get("type") == "run.status" and ((e.get("data") or {}).get("status") != "running"):
                terminal = e
                break
        assert terminal is not None, "expected a terminal run.status event"
        evidence = terminal.get("evidence") or {}
        assert isinstance(evidence.get("events_path"), str) and evidence.get("events_path"), "expected evidence.events_path"
    finally:
        httpd.shutdown()
        httpd.server_close()

