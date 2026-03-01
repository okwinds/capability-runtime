from __future__ import annotations

"""
真实模型集成回归（可选，默认仅在有 .env 时运行）：

- 目标：验证 examples/apps/* 在 `--mode real --non-interactive` 下可端到端跑通，
  并在 workspace 生成最小契约产物（report.md + 至少 1 个结构化文件）。

注意：
- 这些测试会访问真实 OpenAI-compatible provider（需要本地 `.env` 配置）；
- 因此必须标记为 `pytest -m integration`，并在缺少 `.env` 时自动 skip。
"""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from urllib.request import urlopen

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# 集成回归依赖上游网络 client（httpx/anyio）。在部分环境下其连接回收会触发
# `PytestUnraisableExceptionWarning`（通常是 Response/connection pool aclose 在无 event loop 时被回收）。
# 该问题属于上游资源回收时序，不影响本仓“示例可跑通 + 产物/证据链”验收目标，因此在本文件内忽略。
pytestmark = pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")


def _env_exists(app_name: str) -> bool:
    """
    检查 examples/apps/<app_name>/.env 是否存在（集成测试开关）。

    说明：
    - 真实模型（real mode）回归天然具备外部不确定性（费用/外网/敏感信息风险等）；
    - 因此默认 fail-closed：只有显式开启门禁时才允许运行。
    """

    if os.environ.get("CAPRT_TEST_E2E_BRIDGE") != "1":
        return False
    return (_REPO_ROOT / "examples" / "apps" / app_name / ".env").exists()


@pytest.mark.integration
def test_real_form_interview_pro_non_interactive(tmp_path: Path) -> None:
    if not _env_exists("form_interview_pro"):
        pytest.skip("missing examples/apps/form_interview_pro/.env")

    ws = tmp_path / "ws_form_real"
    ws.mkdir(parents=True, exist_ok=True)

    p = subprocess.run(
        [
            sys.executable,
            "examples/apps/form_interview_pro/run.py",
            "--workspace-root",
            str(ws),
            "--mode",
            "real",
            "--non-interactive",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        # 真实模型与内网 provider 的响应时间可能波动较大；此处给足时间避免误报超时。
        timeout=360,
    )
    assert p.returncode == 0, p.stdout + "\n" + p.stderr
    assert (ws / "submission.json").exists()
    assert (ws / "report.md").exists()


@pytest.mark.integration
def test_real_incident_triage_assistant_non_interactive(tmp_path: Path) -> None:
    if not _env_exists("incident_triage_assistant"):
        pytest.skip("missing examples/apps/incident_triage_assistant/.env")

    ws = tmp_path / "ws_incident_real"
    ws.mkdir(parents=True, exist_ok=True)

    p = subprocess.run(
        [
            sys.executable,
            "examples/apps/incident_triage_assistant/run.py",
            "--workspace-root",
            str(ws),
            "--mode",
            "real",
            "--non-interactive",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=360,
    )
    assert p.returncode == 0, p.stdout + "\n" + p.stderr
    assert (ws / "incident.log").exists()
    assert (ws / "runbook.md").exists()
    assert (ws / "report.md").exists()


@pytest.mark.integration
def test_real_ci_failure_triage_and_fix_non_interactive(tmp_path: Path) -> None:
    if not _env_exists("ci_failure_triage_and_fix"):
        pytest.skip("missing examples/apps/ci_failure_triage_and_fix/.env")

    ws = tmp_path / "ws_ci_real"
    ws.mkdir(parents=True, exist_ok=True)

    p = subprocess.run(
        [
            sys.executable,
            "examples/apps/ci_failure_triage_and_fix/run.py",
            "--workspace-root",
            str(ws),
            "--mode",
            "real",
            "--non-interactive",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert p.returncode == 0, p.stdout + "\n" + p.stderr
    assert (ws / "app.py").exists()
    assert (ws / "test_app.py").exists()
    assert (ws / "report.md").exists()


@pytest.mark.integration
def test_real_rules_parser_pro_non_interactive(tmp_path: Path) -> None:
    if not _env_exists("rules_parser_pro"):
        pytest.skip("missing examples/apps/rules_parser_pro/.env")

    ws = tmp_path / "ws_rules_real"
    ws.mkdir(parents=True, exist_ok=True)

    p = subprocess.run(
        [
            sys.executable,
            "examples/apps/rules_parser_pro/run.py",
            "--workspace-root",
            str(ws),
            "--mode",
            "real",
            "--non-interactive",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert p.returncode == 0, p.stdout + "\n" + p.stderr
    assert (ws / "plan.json").exists()
    assert (ws / "result.json").exists()
    assert (ws / "report.md").exists()
    # 结构化文件应是合法 JSON（最小 sanity）
    json.loads((ws / "plan.json").read_text(encoding="utf-8"))
    json.loads((ws / "result.json").read_text(encoding="utf-8"))


def _read_sse_until_terminal(*, url: str, timeout_sec: int = 40) -> dict:
    """读取 SSE 直到收到 terminal 或超时。"""

    with urlopen(url, timeout=timeout_sec) as resp:
        for _ in range(2000):
            line = resp.readline()
            if not line:
                break
            if not line.startswith(b"data: "):
                continue
            payload = json.loads(line[len(b"data: ") :].decode("utf-8"))
            if payload.get("type") == "terminal":
                return payload
    raise AssertionError("no terminal SSE message received")


@pytest.mark.integration
def test_real_sse_gateway_minimal_smoke(tmp_path: Path) -> None:
    if not _env_exists("sse_gateway_minimal"):
        pytest.skip("missing examples/apps/sse_gateway_minimal/.env")

    from examples.apps.sse_gateway_minimal.run import create_server  # type: ignore

    ws = tmp_path / "ws_sse_real"
    ws.mkdir(parents=True, exist_ok=True)

    httpd = create_server(host="127.0.0.1", port=0, mode="real", workspace_root=ws)
    host_raw, port = httpd.server_address[0], int(httpd.server_address[1])
    host = host_raw.decode("utf-8") if isinstance(host_raw, (bytes, bytearray)) else str(host_raw)

    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        with urlopen(f"http://{host}:{port}/start?topic=integration", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        run_id = str(data.get("run_id") or "")
        assert run_id

        # 真实模型在流式场景可能更慢，避免 25s 超时误报
        terminal = _read_sse_until_terminal(url=f"http://{host}:{port}/events?run_id={run_id}", timeout_sec=60)
        assert terminal.get("status") in {"success", "failed", "pending", "cancelled"}
        wal = terminal.get("wal_locator")
        assert isinstance(wal, str) and wal
        assert Path(wal).exists()
        assert (ws / "report.md").exists()
    finally:
        httpd.shutdown()
        httpd.server_close()
