from __future__ import annotations

"""
门禁：docs_for_coding_agent/examples/recipes 离线可回归。

约束：
- 这些配方是“组合示例”，比 atomic 更容易漂移，因此必须纳入 pytest 门禁。
"""

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_example(*, rel_script: str, workspace_root: Path, timeout_sec: int = 90) -> subprocess.CompletedProcess[str]:
    """
    以子进程运行一个 recipe 脚本。

    参数：
    - rel_script：相对仓库根目录的脚本路径
    - workspace_root：该示例的工作区目录
    - timeout_sec：超时秒数（recipe 可能包含 pytest 回归）
    """

    return subprocess.run(
        [sys.executable, rel_script, "--workspace-root", str(workspace_root)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
    )


@pytest.mark.parametrize(
    "rel_script",
    [
        "docs_for_coding_agent/examples/recipes/00_review_fix_qa_report/run.py",
        "docs_for_coding_agent/examples/recipes/01_map_reduce_parallel/run.py",
        "docs_for_coding_agent/examples/recipes/02_policy_references_patch/run.py",
        "docs_for_coding_agent/examples/recipes/03_skill_exec_actions/run.py",
        "docs_for_coding_agent/examples/recipes/04_invoke_capability_child_agent/run.py",
        "docs_for_coding_agent/examples/recipes/05_invoke_capability_child_workflow/run.py",
    ],
)
def test_recipe_examples_offline_smoke(tmp_path: Path, rel_script: str) -> None:
    workspace = tmp_path / ("ws_" + rel_script.replace("/", "_").replace(".", "_"))
    workspace.mkdir(parents=True, exist_ok=True)

    p = _run_example(rel_script=rel_script, workspace_root=workspace, timeout_sec=90)
    assert p.returncode == 0, p.stderr
    assert "EXAMPLE_OK:" in p.stdout, p.stdout

    wal_line = next((x for x in p.stdout.splitlines() if x.startswith("wal_locator=")), "")
    assert wal_line, p.stdout
    wal = wal_line.split("=", 1)[1].strip()
    assert wal
    assert Path(wal).exists()
