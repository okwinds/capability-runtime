from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from capability_runtime.ui_events.v1 import RuntimeEvent


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_jsonl_n(resp, n: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for _ in range(n):
        line = resp.readline()
        if not line:
            break
        out.append(json.loads(line.decode("utf-8")))
    return out


def _post_json(url: str) -> Tuple[int, Dict[str, Any]]:
    req = Request(url, method="POST")
    try:
        with urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {"raw": body}
        return e.code, payload


def test_ui_events_showcase_fixture_is_valid_runtime_event_v1() -> None:
    fixtures_path = _REPO_ROOT / "examples/apps/ui_events_showcase/fixtures/demo.jsonl"
    assert fixtures_path.exists()

    raw = fixtures_path.read_text(encoding="utf-8")
    # 最小披露（离线护栏）：fixtures 不应包含明显 secrets 痕迹
    forbidden_snippets = ["sk-", "Authorization:", "OPENAI_API_KEY=", "password="]
    assert not any(s in raw for s in forbidden_snippets)

    events: List[RuntimeEvent] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        events.append(RuntimeEvent.model_validate_json(line))

    assert events, "fixture must contain at least 1 event"

    # seq monotonic
    seqs = [ev.seq for ev in events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)

    # at least one evidence pointer with events_path
    assert any(ev.evidence is not None and bool(ev.evidence.events_path) for ev in events)

    # at least one tool/approval event (or placeholder)
    assert any(ev.type.startswith("tool.") or ev.type.startswith("approval.") for ev in events)

    # heartbeat + error coverage
    assert any(ev.type == "heartbeat" for ev in events)
    assert any(ev.type == "error" for ev in events)


def test_ui_events_showcase_after_id_is_exclusive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from examples.apps.ui_events_showcase.run import create_server  # type: ignore

    httpd = create_server(host="127.0.0.1", port=0, mode="offline", workspace_root=tmp_path)
    host, port = httpd.server_address[0], int(httpd.server_address[1])

    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        status, started = _post_json(f"http://{host}:{port}/api/start?mode=offline&level=ui")
        assert status == 200, started
        session_id = str(started.get("session_id") or "")
        assert session_id

        with urlopen(
            f"http://{host}:{port}/api/events?session_id={session_id}&transport=jsonl",
            timeout=5,
        ) as resp:
            first_two = _read_jsonl_n(resp, 2)
        assert len(first_two) >= 2
        first_rid = str(first_two[0].get("rid") or "")
        assert first_rid

        with urlopen(
            f"http://{host}:{port}/api/events?session_id={session_id}&transport=jsonl&after_id={first_rid}",
            timeout=5,
        ) as resp2:
            next_one = _read_jsonl_n(resp2, 1)
        assert next_one
        assert str(next_one[0].get("rid") or "") != first_rid
        assert int(next_one[0].get("seq")) > int(first_two[0].get("seq"))
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_ui_events_showcase_sse_framing_is_data_prefix(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from examples.apps.ui_events_showcase.run import create_server  # type: ignore

    httpd = create_server(host="127.0.0.1", port=0, mode="offline", workspace_root=tmp_path)
    host, port = httpd.server_address[0], int(httpd.server_address[1])
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        status, started = _post_json(f"http://{host}:{port}/api/start?mode=offline&level=ui")
        assert status == 200, started
        session_id = str(started.get("session_id") or "")
        assert session_id

        with urlopen(
            f"http://{host}:{port}/api/events?session_id={session_id}&transport=sse",
            timeout=5,
        ) as resp:
            # SSE: data:<json>\n\n (allow empty lines)
            lines: List[str] = []
            while len(lines) < 3:
                b = resp.readline()
                if not b:
                    break
                s = b.decode("utf-8").strip()
                if not s:
                    continue
                lines.append(s)
        assert lines, "expected at least 1 non-empty SSE line"
        assert lines[0].startswith("data:")
        payload = json.loads(lines[0][len("data:") :].strip())
        assert payload.get("schema") == "capability-runtime.runtime_event.v1"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_ui_events_showcase_after_id_invalid_emits_diagnostic_event(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from examples.apps.ui_events_showcase.run import create_server  # type: ignore

    httpd = create_server(host="127.0.0.1", port=0, mode="offline", workspace_root=tmp_path)
    host, port = httpd.server_address[0], int(httpd.server_address[1])
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        status, started = _post_json(f"http://{host}:{port}/api/start?mode=offline&level=ui")
        assert status == 200, started
        session_id = str(started.get("session_id") or "")
        assert session_id

        with urlopen(
            f"http://{host}:{port}/api/events?session_id={session_id}&transport=jsonl&after_id=does_not_exist",
            timeout=5,
        ) as resp:
            got = _read_jsonl_n(resp, 1)
        assert got
        assert str(got[0].get("type") or "") == "error"
        assert "after_id" in str((got[0].get("data") or {}).get("kind") or "") or "after" in str(
            (got[0].get("data") or {}).get("message") or ""
        )
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_ui_events_showcase_real_mode_is_fail_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from examples.apps.ui_events_showcase import run as showcase_run  # type: ignore

    monkeypatch.delenv("CAPRT_TEST_E2E_BRIDGE", raising=False)

    # fail-closed should happen before any real-mode init helpers
    def _boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("real-mode init should not be attempted when gate is closed")

    monkeypatch.setattr(showcase_run, "_load_dotenv_for_real", _boom, raising=False)
    monkeypatch.setattr(showcase_run, "_init_real_provider", _boom, raising=False)

    httpd = showcase_run.create_server(host="127.0.0.1", port=0, mode="offline", workspace_root=tmp_path)
    host, port = httpd.server_address[0], int(httpd.server_address[1])
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        status, payload = _post_json(f"http://{host}:{port}/api/start?mode=real&level=ui")
        assert status == 403
        assert payload.get("error")
    finally:
        httpd.shutdown()
        httpd.server_close()
