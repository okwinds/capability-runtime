from __future__ import annotations

import subprocess
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _git_ls_files(repo_root: Path) -> list[str]:
    """
    返回仓库中所有被 git 跟踪的文件路径（相对 repo root，使用 `/` 分隔）。

    注意：只读取文件名列表，不读取任何 `.env` 内容。
    """

    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:  # pragma: no cover
        raise AssertionError("未找到 `git` 命令，无法执行 repo hygiene 测试。") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise AssertionError(
            "执行 `git ls-files -z` 失败，无法获取被跟踪文件列表。\n"
            f"stderr: {stderr}"
        ) from exc

    raw = completed.stdout
    if not raw:
        return []

    parts = raw.split(b"\x00")
    paths: list[str] = []
    for part in parts:
        if not part:
            continue
        paths.append(part.decode("utf-8", errors="replace"))
    return paths


def test_repo_hygiene_no_tracked_dotenv() -> None:
    """断言：git 跟踪文件中不存在 `(^|/)\\.env$`。"""

    tracked = _git_ls_files(_REPO_ROOT)
    offenders = sorted([p for p in tracked if p == ".env" or p.endswith("/.env")])
    assert offenders == [], f"发现被 git 跟踪的 `.env` 文件（禁止提交）：{offenders}"


def test_repo_hygiene_no_tracked_pyc_or_pycache() -> None:
    """断言：git 跟踪文件中不存在 `\\.pyc$` 或 `(^|/)__pycache__/`。"""

    tracked = _git_ls_files(_REPO_ROOT)
    offenders: list[str] = []
    for path in tracked:
        if path.endswith(".pyc"):
            offenders.append(path)
            continue
        if path.startswith("__pycache__/") or "/__pycache__/" in path:
            offenders.append(path)

    assert offenders == [], (
        "发现被 git 跟踪的缓存产物（禁止提交 `*.pyc` 或 `__pycache__/`）："
        f"{sorted(offenders)}"
    )


def test_examples_apps_each_app_has_env_example() -> None:
    """
    断言：`examples/apps/` 下每个“可运行 app 目录”都存在 `.env.example`。

    “可运行 app 目录”定义：
    - `examples/apps/` 的一级子目录
    - 排除目录名以 `_` 开头
    - 排除 `__pycache__`
    """

    apps_dir = _REPO_ROOT / "examples" / "apps"
    assert apps_dir.is_dir(), f"目录不存在：{apps_dir}"

    app_dirs = [
        p
        for p in apps_dir.iterdir()
        if p.is_dir() and not p.name.startswith("_") and p.name != "__pycache__"
    ]
    assert app_dirs, f"未发现任何 app 目录（按约束过滤后）：{apps_dir}"

    missing: list[str] = []
    for app_dir in sorted(app_dirs, key=lambda p: p.name):
        env_example = app_dir / ".env.example"
        if not env_example.is_file():
            missing.append(str(env_example.relative_to(_REPO_ROOT)))

    assert missing == [], f"以下 app 目录缺少 `.env.example`：{missing}"

