from __future__ import annotations

"""
离线回归护栏：OpenSpec change 必须包含对 docs/specs/ 源规格的引用。

规则：
- 扫描 openspec/changes/ 下所有未归档的 change 目录。
- 对每个 change，检查 proposal.md 和 tasks.md 中是否包含
  至少一个 docs/specs/ 路径引用。
- 缺少引用 → 测试失败。
- 若无未归档 change → 测试直接 pass。

对齐规格：docs/specs/spec-governance-guards-v1.md
"""

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CHANGES_DIR = _REPO_ROOT / "openspec" / "changes"
_ARCHIVE_DIR = _CHANGES_DIR / "archive"

_SPECREF_PATTERN = re.compile(r"docs/specs/[\w._-]+\.md")


def _find_non_archived_changes() -> list[Path]:
    """返回 openspec/changes/ 下所有非 archive 的 change 目录。"""
    if not _CHANGES_DIR.is_dir():
        return []
    result: list[Path] = []
    for child in sorted(_CHANGES_DIR.iterdir()):
        if not child.is_dir():
            continue
        if child.name == "archive":
            continue
        if child.name.startswith("."):
            continue
        result.append(child)
    return result


def _change_has_specref(change_dir: Path) -> bool:
    """
    检查 change 目录的 proposal.md 或 tasks.md 中
    是否包含至少一个 docs/specs/ 路径引用。
    """
    for filename in ("proposal.md", "tasks.md", "spec.md"):
        filepath = change_dir / filename
        if not filepath.is_file():
            continue
        content = filepath.read_text(encoding="utf-8")
        if _SPECREF_PATTERN.search(content):
            return True
    # 也检查 specs/ 子目录下的 spec.md
    specs_subdir = change_dir / "specs"
    if specs_subdir.is_dir():
        for spec_file in specs_subdir.rglob("spec.md"):
            content = spec_file.read_text(encoding="utf-8")
            if _SPECREF_PATTERN.search(content):
                return True
    return False


def test_all_non_archived_changes_have_specref() -> None:
    """
    断言：openspec/changes/ 下所有未归档的 change
    必须在 proposal.md 或 tasks.md 中包含 docs/specs/ 引用。
    """
    changes = _find_non_archived_changes()
    if not changes:
        # 无未归档 change，空集合不算失败
        return

    missing: list[str] = []
    for change_dir in changes:
        if not _change_has_specref(change_dir):
            missing.append(change_dir.name)

    assert missing == [], (
        f"以下 OpenSpec change 缺少对 docs/specs/ 源规格的引用。"
        f"请在 proposal.md 或 tasks.md 中添加 SpecRef "
        f"（格式：docs/specs/<name>.md）。\n"
        f"缺少 SpecRef 的 change：{missing}"
    )


def test_specref_pattern_matches_valid_paths() -> None:
    """单元测试：验证 SpecRef 正则匹配有效路径。"""
    assert _SPECREF_PATTERN.search("参见 docs/specs/node-report-v1.md")
    assert _SPECREF_PATTERN.search("docs/specs/runtime-ui-events-v1.md 定义了")
    assert not _SPECREF_PATTERN.search("openspec/specs/something/spec.md")
    assert not _SPECREF_PATTERN.search("docs/internal/specs/old.md")
