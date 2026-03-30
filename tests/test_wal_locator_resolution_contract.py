from __future__ import annotations

from pathlib import Path

import pytest

from skills_runtime.core.contracts import AgentEvent

from capability_runtime.host_toolkit.resume import load_agent_events_from_locator


def _ev(t: str, *, payload=None) -> AgentEvent:
    return AgentEvent(type=t, timestamp="2026-03-31T00:00:00Z", run_id="r1", payload=payload or {})


def test_load_agent_events_from_locator_reads_filesystem_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("\n".join([_ev("run_started").model_dump_json(), _ev("run_completed").model_dump_json()]) + "\n")

    events = load_agent_events_from_locator(events_path=path)

    assert [ev.type for ev in events] == ["run_started", "run_completed"]


def test_load_agent_events_from_locator_reads_wal_backend_events() -> None:
    class _WalBackend:
        def read_events(self, locator: str):
            assert locator == "wal://run/123"
            return [_ev("run_started"), _ev("run_completed")]

    events = load_agent_events_from_locator(events_path="wal://run/123", wal_backend=_WalBackend())

    assert [ev.type for ev in events] == ["run_started", "run_completed"]


def test_load_agent_events_from_locator_reads_wal_backend_text() -> None:
    raw = "\n".join([_ev("run_started").model_dump_json(), _ev("run_completed").model_dump_json(), ""])

    class _WalBackend:
        def read_text(self, locator: str) -> str:
            assert locator == "wal://run/123"
            return raw

    events = load_agent_events_from_locator(events_path="wal://run/123", wal_backend=_WalBackend())

    assert [ev.type for ev in events] == ["run_started", "run_completed"]


def test_load_agent_events_from_locator_requires_backend_for_wal_locator() -> None:
    with pytest.raises(ValueError, match="wal_backend is required for wal locator"):
        load_agent_events_from_locator(events_path="wal://run/123")


def test_load_agent_events_from_locator_rejects_backend_without_read_api() -> None:
    with pytest.raises(TypeError, match="wal_backend does not support wal locator reads"):
        load_agent_events_from_locator(events_path="wal://run/123", wal_backend=object())


def test_load_agent_events_from_locator_does_not_fallback_to_filesystem_when_wal_read_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _unexpected_read_text(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("should not fallback to Path.read_text")

    monkeypatch.setattr(Path, "read_text", _unexpected_read_text)

    class _WalBackend:
        def read_text(self, locator: str) -> str:
            assert locator == "wal://run/123"
            raise RuntimeError("wal read failed")

    with pytest.raises(RuntimeError, match="wal read failed"):
        load_agent_events_from_locator(events_path="wal://run/123", wal_backend=_WalBackend())
