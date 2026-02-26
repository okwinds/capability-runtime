from __future__ import annotations

"""
离线回归护栏：关键文档/教学包不得再引用 `openspec/changes/*` 作为规范入口。

说明：
- `openspec/changes/` 是过程产物，允许被归档/移动/删除；
- canonical docs 与教学包必须以 `openspec/specs/*` 作为稳定契约入口；
- 本测试刻意不扫描 `openspec/specs/*`：因为 specs 中会以“禁止示例”的形式提到 `openspec/changes/*`。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

import pytest


@dataclass(frozen=True)
class _Hit:
    rel_path: str
    line_no: int
    line: str


def _iter_docs_to_scan(repo_root: Path) -> Iterable[Path]:
    """
    返回需要扫描的文档路径集合（canonical docs + 教学包 + examples README）。

    注意：
    - 不覆盖 docs/internal、docs/context 等追溯材料；
    - 不覆盖 openspec/specs（避免 specs 自身的“禁止示例”触发误报）。
    """

    explicit = [
        repo_root / "DOCS_INDEX.md",
        repo_root / "README.md",
        repo_root / "docs_for_coding_agent" / "capability-coverage-map.md",
        repo_root / "docs_for_coding_agent" / "README.md",
        repo_root / "examples" / "README.md",
    ]
    for p in explicit:
        if p.exists() and p.is_file():
            yield p

    for p in sorted((repo_root / "docs_for_coding_agent").rglob("*.md")):
        if p.name.lower().endswith(".md") and p.is_file():
            yield p

    for p in sorted((repo_root / "examples").rglob("*.md")):
        if p.name.lower().endswith(".md") and p.is_file():
            yield p


def _find_hits(*, repo_root: Path, path: Path, needle: str) -> List[_Hit]:
    """在一个文件中查找 needle，返回命中行列表（用于 fail-fast 取证）。"""

    hits: List[_Hit] = []
    rel = str(path.relative_to(repo_root))
    for idx, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if needle in raw:
            hits.append(_Hit(rel_path=rel, line_no=idx, line=raw.rstrip()))
    return hits


def test_docs_do_not_reference_openspec_changes_as_contract_entry() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    needle = "openspec/changes/"

    all_hits: List[_Hit] = []
    for path in _iter_docs_to_scan(repo_root):
        all_hits.extend(_find_hits(repo_root=repo_root, path=path, needle=needle))

    # 只输出前若干条，避免 pytest 打印过长
    preview: List[Tuple[str, int, str]] = [(h.rel_path, h.line_no, h.line) for h in all_hits[:20]]
    assert all_hits == [], f"Found {len(all_hits)} hits of {needle!r} in canonical docs/teaching pack: {preview}"

