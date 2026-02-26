from __future__ import annotations

"""
离线回归护栏：教学包文档若标注 pinned 上游版本号，则必须与依赖 pin 一致。

背景：
- 本仓升级后容易出现“pyproject.toml 已 pin 新版本，但 Coverage Map 仍写旧版本”的漂移；
- 该测试只对“已显式标注 pinned 版本号”的文档做强一致性约束；
- 若未来决定不再维护 pinned 文本，可删除文档中的版本号标注，此测试会自动跳过。
"""

import re
from pathlib import Path


def _extract_pinned_skills_runtime_sdk_version(pyproject_text: str) -> str:
    m = re.search(r"skills-runtime-sdk==(?P<ver>[0-9A-Za-z.\\-]+)", pyproject_text)
    if not m:
        raise AssertionError("missing skills-runtime-sdk pin in pyproject.toml")
    return str(m.group("ver"))


def test_coverage_map_pinned_version_matches_pyproject() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    pyproject_text = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    pinned = _extract_pinned_skills_runtime_sdk_version(pyproject_text)

    coverage_map = (repo_root / "docs_for_coding_agent" / "capability-coverage-map.md").read_text(encoding="utf-8")
    mentioned = re.findall(r"skills-runtime-sdk==([0-9A-Za-z.\\-]+)", coverage_map)
    if not mentioned:
        return

    assert mentioned == [pinned], f"Coverage Map pinned versions mismatch: {mentioned} (pyproject={pinned})"

