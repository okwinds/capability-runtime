from __future__ import annotations

import subprocess
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]

_FORBIDDEN_EXACT = {
    "AGENTS.md",
    "CLAUDE.md",
    "DOCS_INDEX.md",
    "DOCS_INDEX_TEMPLATE.md",
    "WORKLOG_TEMPLATE.md",
    "TASK_SUMMARY_TEMPLATE.md",
}

_FORBIDDEN_PREFIXES = (
    ".claude/",
    ".codex/",
    "docs/",
    "archive/docs/",
)


def _git_ls_files(repo_root: Path) -> list[str]:
    """返回仓库当前被 Git 跟踪的相对路径列表。"""

    completed = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    raw = completed.stdout
    if not raw:
        return []
    return [
        part.decode("utf-8", errors="replace")
        for part in raw.split(b"\x00")
        if part
    ]


def test_public_repo_has_no_tracked_private_collaboration_assets() -> None:
    """断言：公共仓不再跟踪私有协作文档与私有助手配置。"""

    tracked = _git_ls_files(_REPO_ROOT)
    offenders: list[str] = []
    for path in tracked:
        if path in _FORBIDDEN_EXACT:
            offenders.append(path)
            continue
        if any(path.startswith(prefix) for prefix in _FORBIDDEN_PREFIXES):
            offenders.append(path)
            continue
        if path.startswith("archive/legacy/") and "/docs/" in path:
            offenders.append(path)

    assert offenders == [], (
        "公共仓仍在跟踪私有协作文档/配置，请继续清理："
        f"{sorted(offenders)}"
    )


def test_public_repo_keeps_minimum_public_entrypoints() -> None:
    """断言：公共仓仍保留最小公开入口与示例模板。"""

    assert (_REPO_ROOT / "README.md").is_file(), "README.md 缺失"
    assert (_REPO_ROOT / ".env.example").is_file(), ".env.example 缺失"

