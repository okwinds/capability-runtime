"""最小文件制品存储实现。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FileStore:
    """把运行产物保存为 JSON 文件，按 run_id 分目录。"""

    def __init__(self, base_dir: str = "artifacts") -> None:
        """初始化存储目录，不存在时自动创建。"""
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    def save(self, run_id: str, step_id: str, data: Any) -> Path:
        """保存一个 step 产物，返回写入路径。"""
        path = self.base / run_id / f"{step_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load(self, run_id: str, step_id: str) -> Any | None:
        """读取一个 step 产物；文件不存在时返回 None。"""
        path = self.base / run_id / f"{step_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
