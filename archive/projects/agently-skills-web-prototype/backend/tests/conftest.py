from __future__ import annotations

import sys
from pathlib import Path


def _add_src_to_path() -> None:
    """把 backend 自身 src 与仓库根 src 注入 `sys.path`。"""

    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    for parent in Path(__file__).resolve().parents:
        bridge_src = parent / "src" / "capability_runtime"
        if bridge_src.exists():
            repo_src = parent / "src"
            if str(repo_src) not in sys.path:
                sys.path.insert(0, str(repo_src))
            break


_add_src_to_path()
