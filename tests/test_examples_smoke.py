from __future__ import annotations

"""
示例离线 smoke tests（门禁）：
- 至少覆盖 1 个终端 app（offline）
- 至少覆盖 1 个 HTTP/SSE app（offline）
"""

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.request import urlopen

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _read_sse_until_terminal(*, url: str, timeout_sec: int = 10) -> Dict[str, Any]:
    """
    读取 SSE 直到收到 terminal 消息或超时。

    参数：
    - url：SSE endpoint
    - timeout_sec：总超时秒数

    返回：
    - terminal payload dict
    """

    deadline = time.time() + timeout_sec
    with urlopen(url, timeout=timeout_sec) as resp:
        buf = b""
        while time.time() < deadline:
            chunk = resp.readline()
            if not chunk:
                break
            buf += chunk
            if chunk == b"\n":
                # 一个 SSE message 结束：寻找 data 行
                for line in buf.splitlines():
                    if not line.startswith(b"data: "):
                        continue
                    payload = json.loads(line[len(b"data: ") :].decode("utf-8"))
                    if payload.get("type") == "terminal":
                        return payload
                buf = b""
    raise AssertionError("no terminal SSE message received")


def test_app_form_interview_pro_offline_smoke(tmp_path: Path) -> None:
    workspace = tmp_path / "ws_form"
    workspace.mkdir(parents=True, exist_ok=True)

    p = subprocess.run(
        [
            sys.executable,
            "examples/apps/form_interview_pro/run.py",
            "--workspace-root",
            str(workspace),
            "--mode",
            "offline",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert p.returncode == 0, p.stderr
    assert "EXAMPLE_OK: form_interview_pro" in p.stdout
    assert (workspace / "runtime.yaml").exists()
    assert (workspace / "submission.json").exists()
    assert (workspace / "report.md").exists()

    # wal_locator printed
    wal_line = next((x for x in p.stdout.splitlines() if x.startswith("wal_locator=")), "")
    assert wal_line, p.stdout
    wal_path = wal_line.split("=", 1)[1].strip()
    assert wal_path
    assert Path(wal_path).exists()


def test_app_sse_gateway_minimal_offline_smoke(tmp_path: Path) -> None:
    from examples.apps.sse_gateway_minimal.run import create_server  # type: ignore

    workspace = tmp_path / "ws_sse"
    workspace.mkdir(parents=True, exist_ok=True)

    httpd = create_server(host="127.0.0.1", port=0, mode="offline", workspace_root=workspace)
    host, port = httpd.server_address[0], int(httpd.server_address[1])

    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        start_url = f"http://{host}:{port}/start?topic=smoke"
        with urlopen(start_url, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        run_id = str(data.get("run_id") or "")
        assert run_id

        terminal = _read_sse_until_terminal(url=f"http://{host}:{port}/events?run_id={run_id}", timeout_sec=10)
        assert terminal.get("status") in {"success", "failed", "pending", "cancelled"}
        wal = terminal.get("wal_locator")
        assert isinstance(wal, str) and wal
        assert Path(wal).exists()
        assert (workspace / "report.md").exists()
    finally:
        httpd.shutdown()
        httpd.server_close()
