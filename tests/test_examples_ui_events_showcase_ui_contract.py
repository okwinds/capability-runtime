from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Set


_REPO_ROOT = Path(__file__).resolve().parents[1]


class _IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: Set[str] = set()
        self.attrs_by_id: Dict[str, Dict[str, str]] = {}
        self.details_attrs: List[Dict[str, str]] = []
        self._cur_select_id: str | None = None
        self.select_options: Dict[str, List[Dict[str, str]]] = {}

    def handle_starttag(self, tag: str, attrs: List[tuple[str, str | None]]) -> None:
        d = {k: (v or "") for k, v in attrs}
        if "id" in d and d["id"]:
            self.ids.add(d["id"])
            self.attrs_by_id[d["id"]] = d
        if tag.lower() == "details":
            self.details_attrs.append(d)
        if tag.lower() == "select":
            self._cur_select_id = d.get("id") or None
            if self._cur_select_id:
                self.select_options.setdefault(self._cur_select_id, [])
        if tag.lower() == "option" and self._cur_select_id:
            self.select_options.setdefault(self._cur_select_id, []).append(
                {"value": d.get("value", ""), "selected": "selected" if "selected" in d else ""}
            )

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "select":
            self._cur_select_id = None


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

    # 初始态契约：locator 不可得时按钮应 disabled（spec 语义：“当可得”）
    copy_attrs = p.attrs_by_id.get("copyLocatorBtn") or {}
    assert "disabled" in copy_attrs, "expected copyLocatorBtn to be disabled by default when locator is unavailable"


def test_ui_events_showcase_ui_contract_default_select_values() -> None:
    html_path = _REPO_ROOT / "examples/apps/ui_events_showcase/ui/index.html"
    html = html_path.read_text(encoding="utf-8")

    p = _IdCollector()
    p.feed(html)

    def _assert_selected(select_id: str, value: str) -> None:
        opts = p.select_options.get(select_id) or []
        assert opts, f"expected <select id={select_id!r}> to have <option> children"
        selected = [o.get("value") for o in opts if o.get("selected")]
        assert selected == [value], f"expected {select_id} selected={value!r}, got {selected!r}"

    _assert_selected("modeSelect", "offline")
    _assert_selected("levelSelect", "ui")
    _assert_selected("transportSelect", "sse")


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
