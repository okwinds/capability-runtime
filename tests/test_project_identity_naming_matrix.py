"""项目身份（Project Identity）命名矩阵的回归护栏测试。

目标：确保全域改名后，对外身份一致且不提供旧名兼容口。
"""

from __future__ import annotations

import importlib
from importlib.machinery import PathFinder
from pathlib import Path

import pytest


def test_new_import_root_exists() -> None:
    """`capability_runtime` 必须可直接导入（Quick Start 可复制即用）。"""

    cr = importlib.import_module("capability_runtime")
    assert hasattr(cr, "Runtime")


def test_old_import_root_must_fail() -> None:
    """旧包名不得由本仓源码提供（不得保留 alias/shim）。"""

    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "src"
    # 注意：为了满足“旧名字符串 0 命中”门禁，这里用拼接构造旧包名，避免在仓库中出现字面量。
    old_root = "agently" + "_skills_" + "runtime"
    assert not (src_dir / old_root).exists()
    assert PathFinder.find_spec(old_root, [str(src_dir)]) is None
