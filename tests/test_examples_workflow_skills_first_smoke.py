from __future__ import annotations

"""
示例离线 smoke：examples/05_workflow_skills_first。

约束：
- 不依赖外网/真实 key
- 必须可回归（exit code 0）
"""

import subprocess
import sys
from pathlib import Path


def test_examples_workflow_skills_first_offline_smoke(tmp_path: Path) -> None:
    workspace = tmp_path / "ws_ex_05"
    workspace.mkdir(parents=True, exist_ok=True)

    p = subprocess.run(
        [
            sys.executable,
            "examples/05_workflow_skills_first/run.py",
            "--workspace-root",
            str(workspace),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=40,
    )
    assert p.returncode == 0, p.stderr
    assert "EXAMPLE_OK: examples/05_workflow_skills_first" in p.stdout
