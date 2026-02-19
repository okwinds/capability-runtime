from __future__ import annotations

import sys
from pathlib import Path


# 说明：
# - 本仓库采用 `src/` 布局；
# - 为避免 pytest 在“已安装的 dist 包”与“工作区源码”之间产生歧义，这里显式把 `src/` 放到 sys.path 最前。
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

