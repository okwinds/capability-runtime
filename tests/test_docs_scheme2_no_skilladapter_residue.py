"""离线回归护栏：Scheme2 主线文档不得残留 SkillAdapter 旧叙事关键字。"""

from __future__ import annotations

from pathlib import Path

import pytest


def _read_text(path: Path) -> str:
    """读取 UTF-8 文本文件。"""

    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "relative_path",
    [
        "docs/internal/specs/phases/phase1-protocol-foundation.md",
        "docs/internal/specs/phases/phase2-runtime-layer.md",
        "docs/internal/specs/phases/phase3-adapters-scenarios.md",
        "docs/internal/specs/engineering-spec/03_Security/SKILL_URI_LOADING.md",
        "docs/internal/testing/test-cases/phase1-protocol-foundation-test-cases.md",
        "docs/internal/testing/test-cases/phase2-runtime-layer-test-cases.md",
        "docs/internal/testing/test-cases/phase3-adapters-scenarios-test-cases.md",
        "docs/internal/specs/examples/prototype-validation.md",
        "docs/prd/agently-skills-runtime-capability-runtime.prd.md",
    ],
)
def test_docs_do_not_mention_removed_skill_primitive_terms(relative_path: str) -> None:
    """
    Scheme2 主线护栏：这些文档必须不再出现会误导读者的旧口径关键字。

    注意：该测试只检查“规范性文档集合（canonical set）”，不覆盖 worklog、历史 task summaries、
    decision log 等追溯性文档（它们可能需要在“迁移说明语境”中提及旧术语）。
    """

    repo_root = Path(__file__).resolve().parents[1]
    path = repo_root / relative_path
    if not path.exists():
        pytest.fail(f"Canonical doc file missing: {relative_path}")

    content = _read_text(path)

    forbidden = [
        "SkillAdapter",
        "SkillSpec",
        "CapabilityKind.SKILL",
        "dispatch_rules",
        "inject_to",
        "protocol/skill.py",
        "test_skill.py",
    ]
    hits = [k for k in forbidden if k in content]

    assert hits == [], f"Found deprecated Skill primitive residue in {relative_path}: {hits}"

