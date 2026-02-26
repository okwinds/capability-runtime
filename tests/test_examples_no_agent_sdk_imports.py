from __future__ import annotations

"""
离线回归护栏：主线示例/教学包不得再出现 `agent_sdk.*` import。

说明：
- 本仓主线口径以 `skills_runtime.*` 为准；
- legacy/归档材料允许保留，但不得污染主线示例（examples/ 与 docs_for_coding_agent/examples/）。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple


@dataclass(frozen=True)
class _Hit:
    rel_path: str
    line_no: int
    line: str


def _iter_py_files(repo_root: Path) -> Iterable[Path]:
    for base in [
        repo_root / "examples",
        repo_root / "docs_for_coding_agent" / "examples",
    ]:
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            if p.is_file():
                yield p


def _find_hits(*, repo_root: Path, path: Path, needle: str) -> List[_Hit]:
    hits: List[_Hit] = []
    rel = str(path.relative_to(repo_root))
    for idx, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if needle in raw:
            hits.append(_Hit(rel_path=rel, line_no=idx, line=raw.rstrip()))
    return hits


def test_examples_do_not_import_agent_sdk() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    needle = "agent_sdk."

    all_hits: List[_Hit] = []
    for p in _iter_py_files(repo_root):
        all_hits.extend(_find_hits(repo_root=repo_root, path=p, needle=needle))

    preview: List[Tuple[str, int, str]] = [(h.rel_path, h.line_no, h.line) for h in all_hits[:30]]
    assert all_hits == [], f"Found {len(all_hits)} hits of {needle!r} in examples pack: {preview}"

