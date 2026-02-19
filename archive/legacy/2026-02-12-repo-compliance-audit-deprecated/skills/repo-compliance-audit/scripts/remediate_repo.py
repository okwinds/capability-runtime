#!/usr/bin/env python3
"""
仓库合规整改脚本（Remediation 阶段）

特性：
- 仅对人类选中的 finding.id 执行整改；
- 默认只允许执行 `safe_to_autofix=true` 的修复；
- 默认不覆盖已有文件；
- 目标是“补齐合规缺口”，默认不改业务逻辑。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    """返回 UTC ISO-8601 时间字符串（秒级）。"""

    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析 CLI 参数。"""

    p = argparse.ArgumentParser(description="Repo compliance remediation (selected fixes only).")
    p.add_argument("--repo", type=str, default=".", help="目标仓库路径（默认当前目录）")
    p.add_argument("--findings", type=str, required=True, help="audit 输出的 findings.json 路径")
    p.add_argument(
        "--select",
        type=str,
        default="",
        help="选择要整改的 finding.id（逗号分隔）",
    )
    p.add_argument(
        "--select-file",
        type=str,
        default="",
        help="选择要整改的 finding.id 文件（每行一个）",
    )
    p.add_argument("--overwrite", action="store_true", help="允许覆盖已有文件（默认不覆盖）")
    p.add_argument(
        "--allow-unsafe",
        action="store_true",
        help="允许执行 safe_to_autofix=false 的条目（强烈不建议；默认拒绝）",
    )
    p.add_argument(
        "--report",
        type=str,
        default="",
        help="整改报告输出路径（默认写入 --repo 下 docs/audits 或 /tmp）",
    )
    return p.parse_args(argv)


def resolve_repo_root(repo: Path) -> Path:
    """解析仓库根目录（不依赖 git）。"""

    repo = repo.expanduser().resolve()
    if not repo.exists():
        raise FileNotFoundError(f"--repo 不存在：{repo}")
    if not repo.is_dir():
        raise NotADirectoryError(f"--repo 不是目录：{repo}")
    return repo


def load_findings(findings_path: Path) -> dict[str, Any]:
    """加载 findings.json。"""

    payload = json.loads(findings_path.read_text(encoding="utf-8"))
    if "findings" not in payload or not isinstance(payload["findings"], list):
        raise ValueError("findings.json 结构非法：缺少 findings[]")
    return payload


def load_selected_ids(select: str, select_file: str) -> list[str]:
    """读取人类选中的 finding.id 列表（去重保序）。"""

    ids: list[str] = []
    seen: set[str] = set()

    if select:
        for part in select.split(","):
            v = part.strip()
            if v and v not in seen:
                seen.add(v)
                ids.append(v)

    if select_file:
        p = Path(select_file).expanduser().resolve()
        for raw in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            v = raw.strip()
            if not v or v.startswith("#"):
                continue
            if v not in seen:
                seen.add(v)
                ids.append(v)

    return ids


def _write_file(path: Path, content: str, *, overwrite: bool) -> None:
    """写文件（可选覆盖）。"""

    if path.exists() and not overwrite:
        raise FileExistsError(f"文件已存在且未启用 --overwrite：{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def fix_docs_index(repo_root: Path, *, overwrite: bool) -> str:
    """创建最小 DOCS_INDEX.md 骨架。返回变更说明。"""

    content = "\n".join(
        [
            "# 文档索引（DOCS_INDEX）",
            "",
            "本文件用于登记本仓库关键文档，保证协作可追溯、交付可复现。",
            "",
            "## 规格（Spec）",
            "",
            "- `docs/specs/`：规格/设计文档目录（如适用）。",
            "",
            "## 过程记录",
            "",
            "- `docs/worklog.md`：工作记录（命令、输出、决策与理由）。",
            "- `docs/task-summaries/`：任务总结（范围、变更、测试结果、风险）。",
            "",
        ]
    )
    _write_file(repo_root / "DOCS_INDEX.md", content, overwrite=overwrite)
    return "创建 `DOCS_INDEX.md`（最小索引骨架）。"


def fix_worklog(repo_root: Path, *, overwrite: bool) -> str:
    """创建最小 docs/worklog.md 骨架。返回变更说明。"""

    content = "\n".join(
        [
            "# Worklog（工作记录）",
            "",
            "> 记录每次动手：写 spec / 改代码 / 跑测试 / 做决策。",
            "",
            f"## {_utc_now_iso()}",
            "",
            "- TODO: 记录本次工作内容、命令与输出摘要。",
            "",
        ]
    )
    _write_file(repo_root / "docs/worklog.md", content, overwrite=overwrite)
    return "创建 `docs/worklog.md`（最小 worklog 骨架）。"


def _parse_env_keys(env_text: str) -> list[str]:
    """从 .env 文本提取变量名列表（去重保序）。"""

    keys: list[str] = []
    seen: set[str] = set()
    for raw in env_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if not key or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def fix_env_example(repo_root: Path, *, overwrite: bool) -> str:
    """从 `.env` 生成 `.env.example`（剥离值）。返回变更说明。"""

    env_path = repo_root / ".env"
    if not env_path.exists():
        raise FileNotFoundError("未找到 `.env`，无法生成 `.env.example`。")
    keys = _parse_env_keys(env_path.read_text(encoding="utf-8", errors="ignore"))
    lines = ["# 从 .env 提取变量名生成（已剥离值）", ""]
    for k in keys:
        lines.append(f"{k}=")
    lines.append("")
    _write_file(repo_root / ".env.example", "\n".join(lines), overwrite=overwrite)
    return f"创建 `.env.example`（变量数：{len(keys)}，已剥离值）。"


def default_report_path(repo_root: Path) -> Path:
    """生成默认整改报告路径（优先写入 docs/audits，否则写 /tmp）。"""

    audits_dir = repo_root / "docs/audits/repo-compliance-audit"
    if (repo_root / "docs").exists():
        audits_dir.mkdir(parents=True, exist_ok=True)
        return audits_dir / "remediation_report.md"
    tmp_dir = Path("/tmp/repo-compliance-audit-remediation")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return tmp_dir / "remediation_report.md"


def main(argv: list[str]) -> int:
    """主流程入口。"""

    args = parse_args(argv)
    repo_root = resolve_repo_root(Path(args.repo))
    payload = load_findings(Path(args.findings).expanduser().resolve())
    selected = load_selected_ids(str(args.select).strip(), str(args.select_file).strip())
    if not selected:
        print("未选择任何 finding.id（使用 --select 或 --select-file）。", file=sys.stderr)
        return 2

    findings_by_id: dict[str, dict[str, Any]] = {f.get("id"): f for f in payload["findings"] if isinstance(f, dict)}

    changes: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    for fid in selected:
        f = findings_by_id.get(fid)
        if f is None:
            skipped.append(f"{fid}（未在 findings.json 中找到）")
            continue

        safe = bool(f.get("safe_to_autofix"))
        if not safe and not bool(args.allow_unsafe):
            skipped.append(f"{fid}（safe_to_autofix=false，默认拒绝；如确认可执行使用 --allow-unsafe）")
            continue

        try:
            if fid == "DOCS_INDEX_MISSING":
                changes.append(f"- {fix_docs_index(repo_root, overwrite=bool(args.overwrite))}")
            elif fid == "WORKLOG_MISSING":
                changes.append(f"- {fix_worklog(repo_root, overwrite=bool(args.overwrite))}")
            elif fid == "ENV_EXAMPLE_MISSING":
                changes.append(f"- {fix_env_example(repo_root, overwrite=bool(args.overwrite))}")
            else:
                skipped.append(f"{fid}（当前脚本未提供自动修复器）")
        except Exception as e:  # noqa: BLE001 - 该脚本应记录并继续执行其它条目
            errors.append(f"{fid}: {e}")

    report_path = Path(args.report).expanduser().resolve() if args.report else default_report_path(repo_root)
    report_lines: list[str] = []
    report_lines.append("# Repo Compliance Remediation Report")
    report_lines.append("")
    report_lines.append(f"- 生成时间（UTC）：{_utc_now_iso()}")
    report_lines.append(f"- 仓库根目录：`{repo_root}`")
    report_lines.append(f"- 选择条目：{', '.join(selected)}")
    report_lines.append("")
    report_lines.append("## 已执行变更")
    report_lines.append("")
    report_lines.extend(changes if changes else ["- （无）"])
    report_lines.append("")
    report_lines.append("## 跳过条目")
    report_lines.append("")
    report_lines.extend([f"- {s}" for s in skipped] if skipped else ["- （无）"])
    report_lines.append("")
    report_lines.append("## 错误")
    report_lines.append("")
    report_lines.extend([f"- {e}" for e in errors] if errors else ["- （无）"])
    report_lines.append("")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(f"[repo-compliance-audit] remediation report: {report_path}")
    if errors:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

