from __future__ import annotations

"""
真实模型 evidence-strict 集成回归（可选，默认仅在有 .env 时运行）：

- 目标：验证 examples/apps/* 在 `--mode real --non-interactive --evidence-strict` 下可端到端跑通；
- 重点：strict 模式必须走 tool evidence（禁用 host fallback），并生成契约产物；
- 注意：这些测试会访问真实 OpenAI-compatible provider（需要本地 `.env` 配置），因此必须标记为
  `pytest -m integration`，并在缺少 `.env` 时自动 skip。
"""

import json
import subprocess
import sys
import threading
from pathlib import Path
from urllib.request import urlopen

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

pytestmark = pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")


def _env_exists(app_name: str) -> bool:
    """检查 examples/apps/<app_name>/.env 是否存在（集成测试开关）。"""

    return (_REPO_ROOT / "examples" / "apps" / app_name / ".env").exists()


@pytest.mark.integration
def test_real_form_interview_pro_evidence_strict(tmp_path: Path) -> None:
    if not _env_exists("form_interview_pro"):
        pytest.skip("missing examples/apps/form_interview_pro/.env")

    ws = tmp_path / "ws_form_real_strict"
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
            "--evidence-strict",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert p.returncode == 0, p.stdout + "\n" + p.stderr
    assert (ws / "submission.json").exists()
    assert (ws / "report.md").exists()


@pytest.mark.integration
def test_real_incident_triage_assistant_evidence_strict(tmp_path: Path) -> None:
    if not _env_exists("incident_triage_assistant"):
        pytest.skip("missing examples/apps/incident_triage_assistant/.env")

    ws = tmp_path / "ws_incident_real_strict"
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
            "--evidence-strict",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert p.returncode == 0, p.stdout + "\n" + p.stderr
    assert (ws / "incident.log").exists()
    assert (ws / "runbook.md").exists()
    assert (ws / "report.md").exists()


@pytest.mark.integration
def test_real_rules_parser_pro_evidence_strict(tmp_path: Path) -> None:
    if not _env_exists("rules_parser_pro"):
        pytest.skip("missing examples/apps/rules_parser_pro/.env")

    ws = tmp_path / "ws_rules_real_strict"
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
            "--evidence-strict",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=360,
    )
    assert p.returncode == 0, p.stdout + "\n" + p.stderr
    assert (ws / "plan.json").exists()
    assert (ws / "result.json").exists()
    assert (ws / "report.md").exists()
    json.loads((ws / "plan.json").read_text(encoding="utf-8"))
    json.loads((ws / "result.json").read_text(encoding="utf-8"))


@pytest.mark.integration
def test_real_ci_failure_triage_and_fix_evidence_strict(tmp_path: Path) -> None:
    if not _env_exists("ci_failure_triage_and_fix"):
        pytest.skip("missing examples/apps/ci_failure_triage_and_fix/.env")

    ws = tmp_path / "ws_ci_real_strict"
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
            "--evidence-strict",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=360,
    )
    assert p.returncode == 0, p.stdout + "\n" + p.stderr
    assert (ws / "app.py").exists()
    assert (ws / "test_app.py").exists()
    assert (ws / "report.md").exists()

    # 再跑一次 pytest 做最小真实性校验（修复应生效）。
    p2 = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "test_app.py"],
        cwd=ws,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert p2.returncode == 0, p2.stdout + "\n" + p2.stderr


def _read_sse_until_terminal(*, url: str, timeout_sec: int = 25) -> dict:
    """读取 SSE 直到收到 terminal 或超时。"""

    with urlopen(url, timeout=timeout_sec) as resp:
        for _ in range(4000):
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
def test_real_sse_gateway_minimal_evidence_strict(tmp_path: Path) -> None:
    if not _env_exists("sse_gateway_minimal"):
        pytest.skip("missing examples/apps/sse_gateway_minimal/.env")

    from examples.apps.sse_gateway_minimal.run import create_server  # type: ignore

    ws = tmp_path / "ws_sse_real_strict"
    ws.mkdir(parents=True, exist_ok=True)

    httpd = create_server(host="127.0.0.1", port=0, mode="real", workspace_root=ws)
    host, port = httpd.server_address[0], int(httpd.server_address[1])

    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        with urlopen(f"http://{host}:{port}/start?topic=integration&evidence_strict=1", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        run_id = str(data.get("run_id") or "")
        assert run_id

        terminal = _read_sse_until_terminal(url=f"http://{host}:{port}/events?run_id={run_id}", timeout_sec=40)
        assert terminal.get("status") in {"success", "failed"}, terminal
        if terminal.get("status") == "failed":
            # strict 下缺少 tool evidence 必须 fail-closed（这是“证据严格模式”的预期行为）。
            assert "evidence_strict" in str(terminal.get("error") or "")
        wal = terminal.get("wal_locator")
        assert isinstance(wal, str) and wal
        assert Path(wal).exists()
        # strict 下 report.md 必须来自模型的 file_write evidence；若 terminal=failed 则可能不存在。
        if terminal.get("status") == "success":
            assert (ws / "report.md").exists()
    finally:
        httpd.shutdown()
        httpd.server_close()
