from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _english_docs() -> list[Path]:
    docs = [
        _REPO_ROOT / "README.md",
        _REPO_ROOT / "config" / "README.md",
        _REPO_ROOT / "examples" / "README.md",
        _REPO_ROOT / "docs_for_coding_agent" / "README.md",
        _REPO_ROOT / "docs_for_coding_agent" / "cheatsheet.md",
        _REPO_ROOT / "docs_for_coding_agent" / "00-mental-model.md",
        _REPO_ROOT / "docs_for_coding_agent" / "contract.md",
        _REPO_ROOT / "docs_for_coding_agent" / "capability-coverage-map.md",
        _REPO_ROOT / "help" / "README.md",
    ]
    docs.extend(
        sorted(
            path
            for path in (_REPO_ROOT / "help").glob("[0-9][0-9]-*.md")
            if ".zh-CN." not in path.name
        )
    )
    docs.extend(sorted((_REPO_ROOT / "examples").rglob("README.md")))
    docs.extend(sorted((_REPO_ROOT / "docs_for_coding_agent" / "examples").rglob("README.md")))
    # keep deterministic order without duplicates
    return sorted(dict.fromkeys(docs))


def test_english_docs_have_chinese_pairs_and_links() -> None:
    """公开主文档必须默认英文，并显式链接中文对照页。"""

    for english_path in _english_docs():
        assert english_path.is_file(), f"missing English doc: {english_path.relative_to(_REPO_ROOT)}"
        chinese_path = english_path.with_name(f"{english_path.stem}.zh-CN{english_path.suffix}")
        assert chinese_path.is_file(), f"missing Chinese pair for {english_path.relative_to(_REPO_ROOT)}"
        content = english_path.read_text(encoding="utf-8")
        assert "[中文]" in content, f"missing Chinese link in {english_path.relative_to(_REPO_ROOT)}"
