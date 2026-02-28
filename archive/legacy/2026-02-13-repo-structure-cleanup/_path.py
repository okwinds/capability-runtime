"""
测试辅助：把 `src/` 加到 sys.path。

背景：
- 绝大多数测试文件会 `import _path` 来确保可直接 import `capability_runtime.*`；
- 当用 `python -m unittest discover -s tests -v` 运行时，`tests/_path.py` 可被正确导入；
- 但当直接用 `python -m unittest`（不带 discover 参数）运行时，`tests/` 目录不一定在 sys.path，
  这会导致 `import _path` 失败。

本文件提供一个兼容 shim：
- 让 `import _path` 在任何运行方式下都成立；
- 仅做路径注入，不引入任何业务逻辑（不影响运行时行为）。
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.dirname(__file__))
_SRC = os.path.join(_ROOT, "src")

if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

