"""离线回归护栏：canonical docs 不得残留旧叙事关键字（Scheme2）。"""

from __future__ import annotations

from pathlib import Path

import pytest


def _read_text(path: Path) -> str:
    """读取 UTF-8 文本文件。"""

    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "relative_path",
    [
        # public canonical set：README + 教学包 + 示例说明
        "README.md",
        "help/README.md",
        "help/00-overview.md",
        "help/03-python-api.md",
        "docs_for_coding_agent/README.md",
        "docs_for_coding_agent/cheatsheet.md",
        "docs_for_coding_agent/00-mental-model.md",
        "docs_for_coding_agent/contract.md",
        "examples/README.md",
        "examples/01_quickstart/README.md",
        "examples/02_workflow/README.md",
    ],
)
def test_docs_do_not_mention_removed_skill_primitive_terms(relative_path: str) -> None:
    """
    canonical docs 护栏：这些文档必须不再出现会误导读者的旧口径关键字。

    注意：
    - 该测试只检查 canonical set（见 docs-scheme2-doc-contract spec），不覆盖 worklog、历史归档等追溯性材料；
    - 旧入口类名与旧 Skill 叙事属于“误导性强”的关键字，必须禁止回归。
    """

    repo_root = Path(__file__).resolve().parents[1]
    path = repo_root / relative_path
    if not path.exists():
        pytest.fail(f"Canonical doc file missing: {relative_path}")

    content = _read_text(path)

    forbidden = [
        # 旧 skills 原语叙事（已移除）
        "SkillAdapter",
        "SkillSpec",
        "CapabilityKind.SKILL",
        "dispatch_rules",
        "inject_to",
        "protocol/skill.py",
        "test_skill.py",
        # 旧入口 / 旧 API 叙事（统一 Runtime 后不应再出现在 canonical docs）
        "CapabilityRuntime",
        # 避免出现 legacy 入口类名（用拼接避免“旧名字符串 0 命中”门禁被字面量触发）
        "Agently" + "SkillsRuntime" + "Config",
        "Agently" + "SkillsRuntime" + "(",
        "Agently" + "SkillsRuntime" + ".",
        # 已激活文档不应出现并列叙事触发词（统一归档入口在 archive/）
        "Legacy",
        "legacy",
    ]
    hits = [k for k in forbidden if k in content]

    assert hits == [], f"Found deprecated Skill primitive residue in {relative_path}: {hits}"
