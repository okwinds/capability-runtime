from __future__ import annotations

"""
回归护栏：用户侧文档/示例仅使用包根公共入口。

约束：
- 允许：`from capability_runtime import Runtime, ...`
- 禁止：`from capability_runtime.<submodule> import ...`（深路径不作为对外契约面）

说明：
- 本测试只覆盖“用户可见/可复制粘贴”的入口：README、config/README、help/、examples/、docs_for_coding_agent/。
- tests/ 与 src/ 内部实现可以使用深路径（测试内部模块或模块内相对 import），不在此护栏范围内。
"""

from pathlib import Path
import subprocess

import pytest


_FORBIDDEN_SUBMODULES = (
    "adapters",
    "config",
    "guards",
    "host_toolkit",
    "protocol",
    "registry",
    "reporting",
    "runtime",
    "types",
    "upstream_compat",
)


def _iter_user_facing_files(repo_root: Path) -> list[Path]:
    tracked = {
        Path(part.decode("utf-8", errors="replace"))
        for part in subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.split(b"\x00")
        if part
    }
    targets: list[Path] = []
    for p in [
        repo_root / "README.md",
        repo_root / "config" / "README.md",
    ]:
        rel = p.relative_to(repo_root)
        if p.exists() and rel in tracked:
            targets.append(p)

    config_dir = repo_root / "config"
    if config_dir.exists():
        for ext in (".yaml", ".yml"):
            targets.extend(
                [
                    x
                    for x in config_dir.rglob(f"*{ext}")
                    if x.is_file() and x.relative_to(repo_root) in tracked
                ]
            )

    for base in [repo_root / "help", repo_root / "examples", repo_root / "docs_for_coding_agent"]:
        if not base.exists():
            continue
        for ext in (".py", ".md", ".yaml", ".yml"):
            targets.extend(
                [
                    x
                    for x in base.rglob(f"*{ext}")
                    if x.is_file() and x.relative_to(repo_root) in tracked
                ]
            )

    docs_dir = repo_root / "docs"
    if docs_dir.exists():
        for ext in (".md", ".yaml", ".yml"):
            for x in docs_dir.rglob(f"*{ext}"):
                if not x.is_file():
                    continue
                if x.relative_to(repo_root) not in tracked:
                    continue
                # internal/legacy 文档是“历史取证/归档材料”，允许出现旧名词/旧路径（但必须在文件内显式标注）。
                parts = x.relative_to(repo_root).parts
                if len(parts) >= 2 and parts[0] == "docs" and parts[1] in ("internal", "legacy"):
                    continue
                targets.append(x)
    return targets


@pytest.mark.parametrize("path", _iter_user_facing_files(Path(__file__).resolve().parents[1]))
def test_user_facing_docs_do_not_use_deep_import_paths(path: Path) -> None:
    content = path.read_text(encoding="utf-8")
    for sub in _FORBIDDEN_SUBMODULES:
        needle = f"capability_runtime.{sub}"
        assert needle not in content, f"forbidden deep path reference {needle!r} in {path}"
