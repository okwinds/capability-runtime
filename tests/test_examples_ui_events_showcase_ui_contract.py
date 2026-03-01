from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Set


_REPO_ROOT = Path(__file__).resolve().parents[1]


class _IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: Set[str] = set()
        self.details_attrs: List[Dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, str | None]]) -> None:
        d = {k: (v or "") for k, v in attrs}
        if "id" in d and d["id"]:
            self.ids.add(d["id"])
        if tag.lower() == "details":
            self.details_attrs.append(d)


def test_ui_events_showcase_ui_contract_ids_exist() -> None:
    html_path = _REPO_ROOT / "examples/apps/ui_events_showcase/ui/index.html"
    html = html_path.read_text(encoding="utf-8")

    p = _IdCollector()
    p.feed(html)

    required_ids = {
        # controls
        "modeSelect",
        "levelSelect",
        "transportSelect",
        "connectBtn",
        "disconnectBtn",
        "breakBtn",
        "drawerBtn",
        "themeBtn",
        # layout + panes
        "workflowTree",
        "chatLog",
        "drawer",
        # tabs
        "tabTools",
        "tabTimeline",
        "tabEvidence",
        # evidence fields (copyable locator)
        "eventsPathText",
        "walLocatorText",
        "callIdText",
        "nodeReportSchemaText",
        "rawEvent",
        # copy buttons
        "copyLocatorBtn",
        "copyEventsPathBtn",
        "copyWalLocatorBtn",
        "copyCallIdBtn",
        "copyNodeReportSchemaBtn",
    }
    missing = sorted(required_ids - p.ids)
    assert not missing, f"missing required element ids: {missing}"


def test_ui_events_showcase_minimal_disclosure_details_not_open_by_default() -> None:
    html_path = _REPO_ROOT / "examples/apps/ui_events_showcase/ui/index.html"
    html = html_path.read_text(encoding="utf-8")

    p = _IdCollector()
    p.feed(html)

    assert p.details_attrs, "expected at least one <details> element for raw JSON disclosure gate"
    assert all("open" not in attrs for attrs in p.details_attrs), "<details> must be closed by default (no open attr)"


def test_ui_events_showcase_observation_not_audit_hint_exists() -> None:
    """
    回归护栏：避免把 UI events 当作审计真相源。

    该提示是“贴用户”的必要防误解文案：UI events 是观察流（best-effort），审计/回放需以
    WAL/events + NodeReport 为准。
    """

    html_path = _REPO_ROOT / "examples/apps/ui_events_showcase/ui/index.html"
    html = html_path.read_text(encoding="utf-8")
    assert "观察流" in html and "非审计" in html, "expected UI to clearly state 'observation stream, not audit ledger'"
