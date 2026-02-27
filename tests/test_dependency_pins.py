from __future__ import annotations

from pathlib import Path


def test_dependency_pins_skills_runtime_sdk_version() -> None:
    """
    锁死本仓库对上游 SDK 的依赖 pin，避免后续无意回退/漂移。

    - 入参：无（从仓库根目录读取 `pyproject.toml`）
    - 返回：无；断言失败即视为 pin 被破坏
    """

    repo_root = Path(__file__).resolve().parents[1]
    pyproject_text = (repo_root / "pyproject.toml").read_text(encoding="utf-8")

    assert '"skills-runtime-sdk==0.1.6"' in pyproject_text
    assert '"skills-runtime-sdk==0.1.5.post1"' not in pyproject_text
    assert '"skills-runtime-sdk==1.0.4.post1"' not in pyproject_text
    assert '"skills-runtime-sdk==0.1.4.post2"' not in pyproject_text
