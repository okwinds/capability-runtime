from __future__ import annotations

import sys
from pathlib import Path


def _add_src_to_path() -> None:
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    repo_root = Path(__file__).resolve().parents[4]
    bridge_src = repo_root / "src"
    if str(bridge_src) not in sys.path:
        sys.path.insert(0, str(bridge_src))


_add_src_to_path()
