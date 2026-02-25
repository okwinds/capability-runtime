from __future__ import annotations

"""
门禁：docs_for_coding_agent/examples/atomic 离线可回归。

目标：
- 确保教学示例不会漂移为“只能演示一次”的脚本；
- 每个示例都必须在无网络/无真实 key 环境下稳定跑通；
- 若 stdout 中出现 wal_locator，则必须是可读的本地路径。
"""

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_example(*, rel_script: str, workspace_root: Path, timeout_sec: int = 60) -> subprocess.CompletedProcess[str]:
    """
    以子进程运行一个示例脚本。

    参数：
    - rel_script：相对仓库根目录的脚本路径
    - workspace_root：该示例的工作区目录
    - timeout_sec：超时秒数

    返回：
    - CompletedProcess（stdout/stderr 可用于断言）
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
        "docs_for_coding_agent/examples/atomic/00_runtime_minimal/run.py",
        "docs_for_coding_agent/examples/atomic/01_sdk_native_minimal/run.py",
        "docs_for_coding_agent/examples/atomic/02_read_node_report/run.py",
        "docs_for_coding_agent/examples/atomic/03_preflight_gate/run.py",
        "docs_for_coding_agent/examples/atomic/04_custom_tool/run.py",
        "docs_for_coding_agent/examples/atomic/05_exec_sessions_stub/run.py",
        "docs_for_coding_agent/examples/atomic/06_collab_stub/run.py",
        "docs_for_coding_agent/examples/atomic/07_web_search_offline/run.py",
        "docs_for_coding_agent/examples/atomic/08_view_image_offline/run.py",
    ],
)
def test_atomic_examples_offline_smoke(tmp_path: Path, rel_script: str) -> None:
    workspace = tmp_path / ("ws_" + rel_script.replace("/", "_").replace(".", "_"))
    workspace.mkdir(parents=True, exist_ok=True)

    p = _run_example(rel_script=rel_script, workspace_root=workspace, timeout_sec=60)
    assert p.returncode == 0, p.stderr
    assert "EXAMPLE_OK:" in p.stdout, p.stdout

    # best-effort：若示例打印 wal_locator，则必须存在
    for line in p.stdout.splitlines():
        if not line.startswith("wal_locator="):
            continue
        wal = line.split("=", 1)[1].strip()
        assert wal
        assert Path(wal).exists()

