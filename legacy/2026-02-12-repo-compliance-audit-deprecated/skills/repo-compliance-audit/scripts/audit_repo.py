#!/usr/bin/env python3
"""
仓库合规审计脚本（Audit 阶段）

目标：
- 对指定仓库执行只读合规审计；
- 输出 `report.md`（人类可读）与 `findings.json`（机器可读、可编排）；
- 默认不修改仓库内容（输出写到 --out 指定目录，默认 /tmp）。

注意：
- 本脚本仅使用 Python 标准库；
- 不依赖外网；
- 对“指令遵循性”的判断以可取证证据为准（文件存在性、内容片段、git 状态摘要等），避免臆测。
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Iterator, Literal

VERSION = "0.1"
RedactMode = Literal["none", "report", "all"]


@dataclasses.dataclass(frozen=True)
class EvidenceItem:
    """审计证据条目（用于 report.md 与 findings.json 的取证）。"""

    type: str
    path: str | None = None
    ok: bool | None = None
    message: str | None = None
    data: dict[str, Any] | None = None


@dataclasses.dataclass(frozen=True)
class ProposedFix:
    """建议修复（不等于自动执行；是否可自动执行由 safe_to_autofix 决定）。"""

    kind: str
    path: str | None = None
    notes: str | None = None


@dataclasses.dataclass
class Finding:
    """合规发现条目（稳定 ID + 可取证 + 可整改建议）。"""

    id: str
    title: str
    severity: str
    category: str
    summary: str
    rule_sources: list[str]
    evidence: list[EvidenceItem]
    proposed_fix: ProposedFix | None
    safe_to_autofix: bool
    tags: list[str]
    meta: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 兼容结构。"""

        return {
            "id": self.id,
            "title": self.title,
            "severity": self.severity,
            "category": self.category,
            "summary": self.summary,
            "rule_sources": self.rule_sources,
            "evidence": [dataclasses.asdict(e) for e in self.evidence],
            "proposed_fix": dataclasses.asdict(self.proposed_fix)
            if self.proposed_fix is not None
            else None,
            "safe_to_autofix": self.safe_to_autofix,
            "tags": self.tags,
            "meta": self.meta,
        }


def _utc_now_iso() -> str:
    """返回 UTC ISO-8601 时间字符串（秒级）。"""

    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    """运行子进程并返回 (returncode, stdout)。"""

    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        return p.returncode, p.stdout.strip()
    except FileNotFoundError:
        return 127, ""


def resolve_repo_root(repo: Path) -> Path:
    """尽量解析 git root；非 git 仓库则返回传入路径（要求为目录）。"""

    repo = repo.resolve()
    if not repo.exists():
        raise FileNotFoundError(f"--repo 不存在：{repo}")
    if not repo.is_dir():
        raise NotADirectoryError(f"--repo 不是目录：{repo}")

    code, out = _run(["git", "rev-parse", "--show-toplevel"], cwd=repo)
    if code == 0 and out:
        return Path(out).resolve()
    return repo


def collect_git_meta(repo_root: Path) -> dict[str, Any]:
    """收集 git 元信息（若不是 git 仓库则返回 is_git_repo=false）。"""

    code, top = _run(["git", "rev-parse", "--show-toplevel"], cwd=repo_root)
    if code != 0 or not top:
        return {"is_git_repo": False}

    code, head = _run(["git", "rev-parse", "HEAD"], cwd=repo_root)
    head = head if code == 0 else None

    code, status = _run(["git", "status", "--porcelain"], cwd=repo_root)
    dirty = bool(status.strip()) if code == 0 else None

    code, changed = _run(["git", "diff", "--name-only"], cwd=repo_root)
    changed_files = [line.strip() for line in changed.splitlines() if line.strip()] if code == 0 else []

    code, staged = _run(["git", "diff", "--cached", "--name-only"], cwd=repo_root)
    changed_files_staged = [line.strip() for line in staged.splitlines() if line.strip()] if code == 0 else []

    code, status_all = _run(["git", "status", "--porcelain", "-uall"], cwd=repo_root)
    untracked_files: list[str] = []
    if code == 0:
        for line in status_all.splitlines():
            # porcelain: XY <path> (or ?? <path>)
            if line.startswith("?? "):
                untracked_files.append(line[3:].strip())

    return {
        "is_git_repo": True,
        "head": head,
        "dirty": dirty,
        "changed_files": changed_files,
        "changed_files_staged": changed_files_staged,
        "untracked_files": untracked_files,
    }


def _git_is_tracked(repo_root: Path, rel_path: str) -> bool | None:
    """判断文件是否被 git 跟踪（非 git 仓库或 git 不可用则返回 None）。"""

    code, _ = _run(["git", "rev-parse", "--is-inside-work-tree"], cwd=repo_root)
    if code != 0:
        return None
    code, _ = _run(["git", "ls-files", "--error-unmatch", rel_path], cwd=repo_root)
    return code == 0


def _git_status_porcelain(repo_root: Path, rel_path: str) -> str | None:
    """获取指定路径的 git status porcelain（非 git 仓库或 git 不可用则返回 None）。"""

    code, _ = _run(["git", "rev-parse", "--is-inside-work-tree"], cwd=repo_root)
    if code != 0:
        return None
    code, out = _run(["git", "status", "--porcelain", "--", rel_path], cwd=repo_root)
    if code != 0:
        return None
    return out.strip()


def _git_collect_worktree_changes(repo_root: Path) -> dict[str, list[str]] | None:
    """收集工作区变更（unstaged/staged/untracked）。非 git 仓库则返回 None。"""

    code, _ = _run(["git", "rev-parse", "--is-inside-work-tree"], cwd=repo_root)
    if code != 0:
        return None

    code, unstaged = _run(["git", "diff", "--name-only"], cwd=repo_root)
    code2, staged = _run(["git", "diff", "--cached", "--name-only"], cwd=repo_root)
    code3, status = _run(["git", "status", "--porcelain", "-uall"], cwd=repo_root)
    if code != 0 or code2 != 0 or code3 != 0:
        return None

    untracked: list[str] = []
    for line in status.splitlines():
        if line.startswith("?? "):
            untracked.append(line[3:].strip())

    def _norm(xs: str) -> list[str]:
        return sorted({line.strip() for line in xs.splitlines() if line.strip()})

    return {"unstaged": _norm(unstaged), "staged": _norm(staged), "untracked": sorted(set(untracked))}


def _is_code_path(path: str) -> bool:
    """判断路径是否为“代码变更”（排除 docs/tests 等）。"""

    p = path.lower()
    if p.startswith(("docs/", "doc/")):
        return False
    if p.startswith(("tests/", "test/")):
        return False
    if p.endswith((".md", ".txt")):
        return False
    # 常见代码扩展名（保守）
    return p.endswith(
        (
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".go",
            ".rs",
            ".java",
            ".kt",
            ".cs",
            ".cpp",
            ".c",
            ".h",
            ".hpp",
        )
    )


def _is_spec_related_path(path: str) -> bool:
    """判断路径是否与规格/设计文档强相关。"""

    p = path.lower()
    if p in {"spec_index.md", "spec.md", "docs/spec.md", "docs/spec_index.md", "docs/spec_index.md"}:
        return True
    if p.startswith("docs/specs/") or p.startswith("docs/spec/"):
        return True
    if p.endswith("/spec_index.md"):
        return True
    return False


def check_agents_execution_evidence(
    repo_root: Path,
    agents_text: str,
    rule_sources: list[str],
) -> list[Finding]:
    """
    检查“执行过程是否对齐 AGENTS.md 要求”的可观察证据。

    重要说明：
    - 该检查不读取“代理内部状态/对话”；只基于仓库可观察证据（git 变更集 + worklog 文本信号）。
    - 主要用于“刚执行完一次 agent 操作但尚未提交/尚未整理”的场景：能及时提醒缺少过程证据。
    """

    changes = _git_collect_worktree_changes(repo_root)
    if changes is None:
        return []

    all_changed = sorted(set(changes["unstaged"] + changes["staged"] + changes["untracked"]))
    if not all_changed:
        return []

    has_code_change = any(_is_code_path(p) for p in all_changed)
    has_spec_change = any(_is_spec_related_path(p) for p in all_changed)
    worklog_changed = "docs/worklog.md" in {p.lower() for p in all_changed}

    findings: list[Finding] = []

    # worklog 过程证据（尤其是 code change 的场景）
    worklog_path = repo_root / "docs/worklog.md"
    worklog_text = _read_text_best_effort(worklog_path) if worklog_path.exists() else ""
    worklog_ev = _extract_worklog_test_evidence(worklog_text) if worklog_text else {"command_signals": [], "result_signals": []}

    if has_code_change:
        # Spec-first：代码变更但 spec 相关文件未动（仅做“证据缺失”提示）
        if not has_spec_change:
            findings.append(
                Finding(
                    id="AGENTS_EXECUTION_SPEC_FIRST_EVIDENCE_MISSING",
                    title="本次存在代码变更，但缺少 Spec-first 的过程证据",
                    severity="medium",
                    category="instruction",
                    summary="检测到工作区包含代码变更，但变更集中没有 spec/规格相关文件。若 AGENTS 要求 Spec-first，请补齐过程证据。",
                    rule_sources=rule_sources,
                    evidence=[
                        EvidenceItem(type="worktree_changes", ok=False, data={"changed": all_changed[:80]}),
                        EvidenceItem(type="has_code_change", ok=True),
                        EvidenceItem(type="has_spec_change", ok=False),
                    ],
                    proposed_fix=ProposedFix(
                        kind="manual_update_spec",
                        notes="建议补齐/更新 spec（Goal/Constraints/Contract/AC/Test Plan），并在 worklog 记录原因与取舍。",
                    ),
                    safe_to_autofix=False,
                    tags=["instruction", "spec-first", "evidence"],
                    meta={"changed_count": len(all_changed)},
                )
            )

        # Test evidence：代码变更但 worklog 中缺少测试命令+结果信号
        if not (worklog_ev["command_signals"] and worklog_ev["result_signals"]):
            findings.append(
                Finding(
                    id="AGENTS_EXECUTION_TEST_EVIDENCE_MISSING",
                    title="本次存在代码变更，但缺少离线回归/TDD 的过程证据",
                    severity="high",
                    category="instruction",
                    summary="检测到工作区包含代码变更，但 worklog 中缺少测试命令与结果记录信号。无法取证“完成=测试通过”。",
                    rule_sources=rule_sources,
                    evidence=[
                        EvidenceItem(type="worktree_changes", ok=False, data={"changed": all_changed[:80]}),
                        EvidenceItem(type="worklog_test_evidence", ok=False, data=worklog_ev),
                    ],
                    proposed_fix=ProposedFix(
                        kind="manual_run_tests_and_record",
                        notes="建议运行离线回归测试并将命令+结果写入 worklog；必要时在 CI 增加门禁。",
                    ),
                    safe_to_autofix=False,
                    tags=["instruction", "tdd", "evidence"],
                    meta={"changed_count": len(all_changed)},
                )
            )

        # Worklog evidence：代码变更但 worklog 未同步更新
        if not worklog_changed:
            findings.append(
                Finding(
                    id="AGENTS_EXECUTION_WORKLOG_EVIDENCE_MISSING",
                    title="本次存在代码变更，但 worklog 未同步更新（证据缺失）",
                    severity="medium",
                    category="instruction",
                    summary="检测到工作区包含代码变更，但变更集中未包含 `docs/worklog.md`。若 AGENTS 要求“每次动手都要记 worklog”，请补齐。",
                    rule_sources=rule_sources,
                    evidence=[
                        EvidenceItem(type="worktree_changes", ok=False, data={"changed": all_changed[:80]}),
                        EvidenceItem(type="worklog_changed", ok=False, data={"path": "docs/worklog.md"}),
                    ],
                    proposed_fix=ProposedFix(
                        kind="manual_update_worklog",
                        notes="建议补齐 worklog：记录本次工作、命令、输出摘要、决策与理由。",
                    ),
                    safe_to_autofix=False,
                    tags=["instruction", "worklog", "evidence"],
                    meta={"changed_count": len(all_changed)},
                )
            )

    return findings


def check_agents_integrity(repo_root: Path, rule_sources: list[str]) -> list[Finding]:
    """
    审查规则文件（AGENTS.md）的完整性与可追溯性。

    关注点（你强调的风险）：
    - 文件被删除；
    - 文件存在但未被版本控制（容易被悄悄篡改）；
    - 文件在工作区被修改（dirty），属于“规则被改动”的强信号。
    """

    findings: list[Finding] = []
    rel = "AGENTS.md"
    agents_path = repo_root / rel

    tracked = _git_is_tracked(repo_root, rel)
    status = _git_status_porcelain(repo_root, rel)

    if not agents_path.exists():
        # 如果 git 跟踪过但文件不存在，优先提升为“疑似删除”
        if tracked is True:
            findings.append(
                Finding(
                    id="AGENTS_MD_DELETED",
                    title="规则文件 AGENTS.md 被删除/缺失（git 跟踪过）",
                    severity="high",
                    category="instruction",
                    summary="AGENTS.md 曾被 git 跟踪，但当前工作区缺失。可能是误删或被篡改删除，需要立即人工核查。",
                    rule_sources=rule_sources or ["git 取证（规则文件完整性）"],
                    evidence=[
                        _path_exists_evidence(repo_root, rel),
                        EvidenceItem(type="git_tracked", ok=True, data={"path": rel}),
                        EvidenceItem(type="git_status_porcelain", ok=False, data={"path": rel, "status": status or ""}),
                    ],
                    proposed_fix=ProposedFix(
                        kind="manual_restore",
                        notes="建议人工核查：确认删除原因 → 从 git 恢复 → 建议在 CI 增加规则文件存在性门禁。",
                    ),
                    safe_to_autofix=False,
                    tags=["instruction", "rules", "integrity"],
                    meta={},
                )
            )
        else:
            # 非 git 仓库或未跟踪：只做 info 提示
            findings.append(
                Finding(
                    id="AGENTS_MD_MISSING",
                    title="未发现 AGENTS.md（缺少显式协作规则）",
                    severity="info",
                    category="instruction",
                    summary="未在仓库根目录发现 `AGENTS.md`。若团队存在其它规则文件，请以其为准并补充审计口径。",
                    rule_sources=["规则文件存在性检查"],
                    evidence=[_path_exists_evidence(repo_root, rel)],
                    proposed_fix=ProposedFix(
                        kind="manual_confirm_rules",
                        notes="建议人工确认规则来源（CONTRIBUTING/docs/process 等），或补齐 AGENTS.md。",
                    ),
                    safe_to_autofix=False,
                    tags=["instruction", "rules"],
                    meta={},
                )
            )
        return findings

    # 存在但未被跟踪：中风险（可被悄悄改）
    if tracked is False:
        findings.append(
            Finding(
                id="AGENTS_MD_UNTRACKED",
                title="规则文件 AGENTS.md 未纳入版本控制（可追溯性风险）",
                severity="medium",
                category="instruction",
                summary="AGENTS.md 存在但未被 git 跟踪，规则可能在无审查流程下被修改。建议纳入版本控制并走代码审查。",
                rule_sources=rule_sources or ["git 取证（规则文件完整性）"],
                evidence=[
                    _path_exists_evidence(repo_root, rel),
                    EvidenceItem(type="git_tracked", ok=False, data={"path": rel}),
                    EvidenceItem(type="git_status_porcelain", ok=False, data={"path": rel, "status": status or ""}),
                ],
                proposed_fix=ProposedFix(
                    kind="manual_git_add",
                    notes="建议人工执行：git add AGENTS.md 并通过正常 review/CI 流程合入。",
                ),
                safe_to_autofix=False,
                tags=["instruction", "rules", "integrity"],
                meta={},
            )
        )

    # 工作区被修改：强信号（规则被改）
    if status and tracked is True:
        findings.append(
            Finding(
                id="AGENTS_MD_MODIFIED",
                title="规则文件 AGENTS.md 在工作区被修改（强信号）",
                severity="high",
                category="instruction",
                summary="检测到 AGENTS.md 的 git status 非干净状态（porcelain 非空）。规则文件变更应被视为高风险，需人工核查与审查。",
                rule_sources=rule_sources or ["git 取证（规则文件完整性）"],
                evidence=[
                    _path_exists_evidence(repo_root, rel),
                    EvidenceItem(type="git_tracked", ok=True, data={"path": rel}),
                    EvidenceItem(type="git_status_porcelain", ok=False, data={"path": rel, "status": status}),
                ],
                proposed_fix=ProposedFix(
                    kind="manual_review_required",
                    notes="建议人工核查修改内容；若为恶意/误改应回滚；如为合理更新需走评审并同步更新相关 spec/test gate。",
                ),
                safe_to_autofix=False,
                tags=["instruction", "rules", "integrity"],
                meta={},
            )
        )

    return findings


def _looks_like_repo_path(token: str) -> bool:
    """用启发式判断 backtick token 是否可能是仓库路径。"""

    if " " in token or "\t" in token:
        return False
    if token.startswith("http://") or token.startswith("https://"):
        return False
    if token.startswith("@"):
        return False
    if token.startswith("--"):
        return False
    if token.endswith((".md", ".txt", ".yml", ".yaml", ".json", ".toml", ".env")):
        return True
    if "/" in token:
        return True
    return False


def extract_agents_required_paths(agents_text: str) -> set[str]:
    """
    从 AGENTS.md 文本中提取“强约束路径”（启发式）。

    设计原则：
    - 只抽取“明显像路径”的 backtick token；
    - 尽量聚焦于常见强约束段落（文档索引/推荐默认值/完成定义）。
    """

    required: set[str] = set()

    focus_markers = (
        "推荐默认值",
        "文档索引",
        "工作记录",
        "任务总结",
        "完成定义",
        "Definition of Done",
    )

    lines = agents_text.splitlines()
    focused_lines: list[str] = []
    for line in lines:
        if any(marker in line for marker in focus_markers):
            focused_lines.append(line)
            continue
        if focused_lines:
            focused_lines.append(line)

    # 兜底：若没抓到 focus，则退化为全文件扫描
    scan_text = "\n".join(focused_lines) if focused_lines else agents_text

    for token in re.findall(r"`([^`]+)`", scan_text):
        token = token.strip()
        if _looks_like_repo_path(token):
            required.add(token)
    return required


def _path_exists_evidence(repo_root: Path, rel_path: str) -> EvidenceItem:
    """构造 path_exists 类型证据。"""

    ok = (repo_root / rel_path).exists()
    return EvidenceItem(type="path_exists", path=rel_path, ok=ok)


def _ensure_finding(
    findings: list[Finding],
    *,
    id: str,
    title: str,
    severity: str,
    category: str,
    summary: str,
    rule_sources: list[str],
    evidence: list[EvidenceItem],
    proposed_fix: ProposedFix | None,
    safe_to_autofix: bool,
    tags: list[str],
    meta: dict[str, Any] | None = None,
) -> None:
    """追加 finding（保持结构一致，避免遗漏字段）。"""

    findings.append(
        Finding(
            id=id,
            title=title,
            severity=severity,
            category=category,
            summary=summary,
            rule_sources=rule_sources,
            evidence=evidence,
            proposed_fix=proposed_fix,
            safe_to_autofix=safe_to_autofix,
            tags=tags,
            meta=meta or {},
        )
    )


def check_docs_index(repo_root: Path, rule_sources: list[str]) -> Finding | None:
    """检查 DOCS_INDEX.md 是否存在。"""

    rel_path = "DOCS_INDEX.md"
    ev = _path_exists_evidence(repo_root, rel_path)
    if ev.ok:
        return None

    return Finding(
        id="DOCS_INDEX_MISSING",
        title="缺少文档索引 DOCS_INDEX.md",
        severity="high",
        category="docs",
        summary="仓库缺少关键文档索引，难以协作追溯与复现。",
        rule_sources=rule_sources,
        evidence=[ev],
        proposed_fix=ProposedFix(
            kind="create_file",
            path=rel_path,
            notes="生成最小可用索引骨架，后续由人类补齐。",
        ),
        safe_to_autofix=True,
        tags=["docs", "index"],
        meta={},
    )


def check_worklog(repo_root: Path, rule_sources: list[str]) -> Finding | None:
    """检查 docs/worklog.md 是否存在。"""

    rel_path = "docs/worklog.md"
    ev = _path_exists_evidence(repo_root, rel_path)
    if ev.ok:
        return None

    return Finding(
        id="WORKLOG_MISSING",
        title="缺少工作记录 docs/worklog.md",
        severity="medium",
        category="docs",
        summary="缺少 worklog 会导致无法取证“做了什么/为何这么做/怎么复现”。",
        rule_sources=rule_sources,
        evidence=[ev],
        proposed_fix=ProposedFix(
            kind="create_file",
            path=rel_path,
            notes="创建最小 worklog 骨架（含日期分段与命令记录位）。",
        ),
        safe_to_autofix=True,
        tags=["docs", "worklog"],
        meta={},
    )


def _read_text_best_effort(path: Path, *, max_bytes: int = 512_000) -> str:
    """尽力读取文本文件（限制最大字节，避免巨文件）。"""

    try:
        st = path.stat()
        if st.st_size > max_bytes:
            return ""
    except OSError:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _has_test_suite_indicators(repo_root: Path) -> tuple[bool, list[str]]:
    """判断仓库是否存在“测试工程/测试运行”指示器（启发式）。"""

    indicators: list[str] = []
    candidates = [
        "tests",
        "test",
        "pytest.ini",
        "pyproject.toml",
        "package.json",
        "go.mod",
        "Cargo.toml",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "Makefile",
    ]
    for rel in candidates:
        p = repo_root / rel
        if p.exists():
            indicators.append(rel)

    # 进一步：pyproject.toml 中是否存在 pytest/unittest 关键字
    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists():
        text = _read_text_best_effort(pyproject)
        if re.search(r"\bpytest\b", text):
            indicators.append("pyproject.toml:pytest")

    pkg = repo_root / "package.json"
    if pkg.exists():
        text = _read_text_best_effort(pkg)
        if re.search(r"\"test\"\s*:", text):
            indicators.append("package.json:scripts.test")

    return (len(indicators) > 0), sorted(set(indicators))


def _extract_worklog_test_evidence(worklog_text: str) -> dict[str, Any]:
    """从 worklog 中提取“离线回归执行证据”（启发式，不做真假断言）。"""

    patterns = [
        r"\bpytest\b",
        r"\bunittest\b",
        r"\bnpm\s+test\b",
        r"\bpnpm\s+test\b",
        r"\byarn\s+test\b",
        r"\bcargo\s+test\b",
        r"\bgo\s+test\b",
        r"\bdotnet\s+test\b",
        r"\bmvn\s+test\b",
        r"\bgradle\s+test\b",
        r"/usr/bin/python3\s+-m\s+unittest\b",
    ]
    hits: list[str] = []
    for pat in patterns:
        if re.search(pat, worklog_text):
            hits.append(pat)

    # 结果关键词（弱信号）
    result_hits = []
    for pat in [r"\bOK\b", r"PASS", r"通过", r"成功", r"0\s+fail", r"0\s+failed"]:
        if re.search(pat, worklog_text, flags=re.IGNORECASE):
            result_hits.append(pat)

    return {"command_signals": hits, "result_signals": result_hits}


def check_spec_entrypoint_and_sections(
    repo_root: Path,
    rule_sources: list[str],
) -> list[Finding]:
    """检查 Spec-first 的可观察证据：是否存在 spec 入口，是否包含关键章节（启发式）。"""

    findings: list[Finding] = []

    candidates = [
        "docs/spec.md",
        "docs/SPEC_INDEX.md",
        "docs/specs/SPEC_INDEX.md",
        "SPEC_INDEX.md",
        "spec.md",
        "SPEC.md",
    ]

    # 扫描 docs/specs 下的一些常见入口
    specs_dir = repo_root / "docs/specs"
    if specs_dir.exists() and specs_dir.is_dir():
        for p in specs_dir.rglob("SPEC_INDEX.md"):
            try:
                rel = str(p.relative_to(repo_root))
            except ValueError:
                continue
            candidates.append(rel)

    existing = []
    for rel in candidates:
        p = repo_root / rel
        if p.exists() and p.is_file():
            existing.append(rel)

    if not existing:
        findings.append(
            Finding(
                id="SPEC_ENTRYPOINT_MISSING",
                title="缺少 Spec 入口文件（Spec-first 证据不足）",
                severity="medium",
                category="spec",
                summary="未检测到常见 spec 入口（如 `docs/spec.md`、`SPEC_INDEX.md` 等）。",
                rule_sources=rule_sources,
                evidence=[EvidenceItem(type="spec_entrypoint_candidates", ok=False, data={"checked": sorted(set(candidates))[:50]})],
                proposed_fix=ProposedFix(
                    kind="manual_create_spec_entrypoint",
                    notes="建议补齐 spec 入口与索引，并包含验收标准与测试计划。",
                ),
                safe_to_autofix=False,
                tags=["spec-first", "documentation"],
                meta={},
            )
        )
        return findings

    # 只选前若干个入口做章节检查，避免成本过高
    section_markers = {
        "goal": [r"\bGoal\b", "目标"],
        "constraints": [r"\bConstraints\b", "约束"],
        "contract": [r"\bContract\b", "契约", "协议"],
        "ac": [r"\bAcceptance Criteria\b", "验收标准"],
        "test_plan": [r"\bTest Plan\b", "测试计划"],
    }

    checked = []
    best = {"path": None, "present": 0, "present_keys": []}
    for rel in existing[:8]:
        text = _read_text_best_effort(repo_root / rel)
        present_keys = []
        for key, markers in section_markers.items():
            if any(re.search(m, text, flags=re.IGNORECASE) for m in markers):
                present_keys.append(key)
        checked.append({"path": rel, "present": present_keys})
        if len(present_keys) > best["present"]:
            best = {"path": rel, "present": len(present_keys), "present_keys": present_keys}

    # 若最佳入口覆盖不足，则提示缺章节
    if best["present"] < 3:
        findings.append(
            Finding(
                id="SPEC_REQUIRED_SECTIONS_MISSING",
                title="Spec 入口缺少关键章节（可复刻性风险）",
                severity="medium",
                category="spec",
                summary="检测到 spec 入口文件，但关键章节覆盖不足（Goal/Constraints/Contract/AC/Test Plan）。",
                rule_sources=rule_sources,
                evidence=[
                    EvidenceItem(type="spec_section_check", ok=False, data={"checked": checked, "best": best}),
                ],
                proposed_fix=ProposedFix(
                    kind="manual_fill_sections",
                    notes="建议补齐缺失章节，并在 Test Plan 中给出离线回归命令与预期结果。",
                ),
                safe_to_autofix=False,
                tags=["spec-first", "replicability"],
                meta={},
            )
        )

    return findings


def _chinese_ratio(text: str) -> float:
    """粗略估算中文字符比例（启发式）。"""

    if not text:
        return 0.0
    total = 0
    cjk = 0
    for ch in text:
        if ch.isspace():
            continue
        total += 1
        if "\u4e00" <= ch <= "\u9fff":
            cjk += 1
    if total == 0:
        return 0.0
    return cjk / total


def check_chinese_doc_language(
    repo_root: Path, agents_text: str, rule_sources: list[str]
) -> Finding | None:
    """若规则要求中文文档，则对关键文档做启发式语言比例提示。"""

    if not re.search(r"中文", agents_text):
        return None

    paths = ["README.md", "DOCS_INDEX.md", "docs/spec.md", "docs/SPEC_INDEX.md"]
    checked: list[dict[str, Any]] = []
    ratios = []
    for rel in paths:
        p = repo_root / rel
        if not p.exists() or not p.is_file():
            continue
        text = _read_text_best_effort(p, max_bytes=256_000)
        ratio = _chinese_ratio(text)
        checked.append({"path": rel, "chinese_ratio": ratio})
        ratios.append(ratio)

    if not checked:
        return None

    # 阈值较保守：仅提示，不做强断言
    if max(ratios) >= 0.15:
        return None

    return Finding(
        id="DOC_LANGUAGE_POSSIBLE_VIOLATION",
        title="文档语言可能不符合“中文”约束（启发式提示）",
        severity="info",
        category="instruction",
        summary="规则文件包含中文语言约束，但关键文档的中文比例偏低（启发式）。请人工复核。",
        rule_sources=rule_sources,
        evidence=[EvidenceItem(type="chinese_ratio_check", ok=False, data={"checked": checked})],
        proposed_fix=ProposedFix(
            kind="manual_review",
            notes="建议人工确认语言约束策略（中文/双语），并补齐关键文档说明。",
        ),
        safe_to_autofix=False,
        tags=["language", "instruction"],
        meta={},
    )


def check_tdd_evidence(
    repo_root: Path,
    rule_sources: list[str],
) -> Finding | None:
    """检查是否存在 TDD/离线回归的可观察证据（启发式）。"""

    has_suite, suite_indicators = _has_test_suite_indicators(repo_root)

    worklog_path = repo_root / "docs/worklog.md"
    worklog_text = _read_text_best_effort(worklog_path) if worklog_path.exists() else ""
    worklog_ev = _extract_worklog_test_evidence(worklog_text) if worklog_text else {"command_signals": [], "result_signals": []}

    ok = has_suite and bool(worklog_ev["command_signals"]) and bool(worklog_ev["result_signals"])
    if ok:
        return None

    # 若缺少 worklog，本项不重复报（由 WORKLOG_MISSING 覆盖），但仍记录测试工程缺失
    if not worklog_path.exists() and not has_suite:
        return Finding(
            id="TDD_EVIDENCE_MISSING",
            title="缺少离线回归/TDD 的证据（无测试工程痕迹，且无 worklog）",
            severity="high",
            category="testing",
            summary="未检测到测试工程指示器，且缺少 worklog，无法证明“完成=测试通过”。",
            rule_sources=rule_sources,
            evidence=[
                EvidenceItem(type="test_suite_indicators", ok=False, data={"has_suite": has_suite, "indicators": suite_indicators}),
                EvidenceItem(type="worklog_present", ok=False, path="docs/worklog.md"),
            ],
            proposed_fix=ProposedFix(
                kind="manual_add_tests_and_record",
                notes="建议补齐离线回归测试，并在 worklog 记录命令与结果；CI 可选加门禁。",
            ),
            safe_to_autofix=False,
            tags=["tdd", "testing", "evidence"],
            meta={"has_suite": has_suite},
        )

    if not has_suite:
        return Finding(
            id="TDD_EVIDENCE_MISSING",
            title="缺少离线回归/TDD 的证据（测试工程痕迹不足）",
            severity="medium",
            category="testing",
            summary="未检测到常见测试工程指示器（tests/、pytest、scripts.test 等），无法证明 TDD 落地。",
            rule_sources=rule_sources,
            evidence=[
                EvidenceItem(type="test_suite_indicators", ok=False, data={"has_suite": has_suite, "indicators": suite_indicators}),
                EvidenceItem(type="worklog_test_evidence", ok=bool(worklog_ev["command_signals"]), data=worklog_ev),
            ],
            proposed_fix=ProposedFix(
                kind="manual_add_tests_and_record",
                notes="建议补齐离线回归测试，并在 worklog 记录命令与结果。",
            ),
            safe_to_autofix=False,
            tags=["tdd", "testing"],
            meta={"has_suite": has_suite},
        )

    # has suite but no recorded evidence
    if worklog_path.exists() and (not worklog_ev["command_signals"] or not worklog_ev["result_signals"]):
        return Finding(
            id="TDD_EVIDENCE_MISSING",
            title="缺少离线回归/TDD 的证据（worklog 未记录测试命令/结果）",
            severity="medium",
            category="testing",
            summary="检测到测试工程痕迹，但 worklog 中缺少测试命令与结果记录（启发式）。",
            rule_sources=rule_sources,
            evidence=[
                EvidenceItem(type="test_suite_indicators", ok=True, data={"has_suite": has_suite, "indicators": suite_indicators}),
                EvidenceItem(type="worklog_test_evidence", ok=False, data=worklog_ev),
            ],
            proposed_fix=ProposedFix(
                kind="manual_record_worklog",
                notes="建议将离线回归命令与结果写入 worklog，满足可取证要求。",
            ),
            safe_to_autofix=False,
            tags=["tdd", "worklog"],
            meta={"has_suite": has_suite},
        )

    return None


def _parse_env_lines(env_text: str) -> list[str]:
    """解析 .env 文本并返回变量名列表（去重，保序）。"""

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


def check_env_example(repo_root: Path, rule_sources: list[str]) -> Finding | None:
    """检查存在 .env 但缺少 .env.example。"""

    env_path = repo_root / ".env"
    if not env_path.exists():
        return None

    example_path = repo_root / ".env.example"
    if example_path.exists():
        return None

    ev: list[EvidenceItem] = [
        EvidenceItem(type="path_exists", path=".env", ok=True),
        EvidenceItem(type="path_exists", path=".env.example", ok=False),
    ]

    # 取证：仅记录 key 数量，不记录 value
    try:
        keys = _parse_env_lines(env_path.read_text(encoding="utf-8", errors="ignore"))
        ev.append(EvidenceItem(type="env_keys_detected", ok=True, data={"count": len(keys)}))
    except OSError as e:
        ev.append(EvidenceItem(type="env_read_error", ok=False, message=str(e)))

    return Finding(
        id="ENV_EXAMPLE_MISSING",
        title="缺少 .env.example（存在 .env）",
        severity="high",
        category="repro",
        summary="存在 `.env` 但缺少 `.env.example`，会降低可复现性且增加密钥误提交风险。",
        rule_sources=rule_sources,
        evidence=ev,
        proposed_fix=ProposedFix(
            kind="create_file_from_env_keys",
            path=".env.example",
            notes="从 `.env` 提取变量名并剥离值生成 `.env.example`（不得复制真实值）。",
        ),
        safe_to_autofix=True,
        tags=["env", "reproducibility", "security"],
        meta={},
    )


def _should_skip_dir(name: str) -> bool:
    """判断目录名是否应跳过扫描（减少噪声与性能开销）。"""

    return name in {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        "dist",
        "build",
        ".DS_Store",
    }


def iter_candidate_files(repo_root: Path, *, max_bytes: int) -> Iterator[Path]:
    """遍历候选文件（跳过常见大目录、二进制/超大文件）。"""

    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if not _should_skip_dir(d)]
        for f in files:
            p = Path(root) / f
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_size > max_bytes:
                continue
            # 跳过明显的二进制（粗略判断：扩展名）
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".tar", ".gz", ".ico"}:
                continue
            yield p


def scan_possible_secrets(repo_root: Path) -> list[EvidenceItem]:
    """
    扫描疑似密钥/私钥/令牌。

    说明：
    - 仅用于提示风险（可能误报）；
    - 默认限制文件大小，避免扫描耗时过大；
    - 证据里不输出完整命中内容（防止二次泄露），仅输出规则名 + 文件 + 行号。
    """

    patterns: list[tuple[str, re.Pattern[str]]] = [
        ("PRIVATE_KEY_BLOCK", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----")),
        ("AWS_ACCESS_KEY_ID", re.compile(r"AKIA[0-9A-Z]{16}")),
        ("SLACK_TOKEN", re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}")),
        ("OPENAI_LIKE_TOKEN", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ]

    hits: list[dict[str, Any]] = []
    max_files = 3000
    max_hits = 200
    scanned = 0

    for p in iter_candidate_files(repo_root, max_bytes=512_000):
        scanned += 1
        if scanned > max_files:
            break

        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for i, line in enumerate(text.splitlines(), start=1):
            for label, rx in patterns:
                if rx.search(line):
                    hits.append(
                        {
                            "rule": label,
                            "path": str(p.relative_to(repo_root)),
                            "line": i,
                        }
                    )
                    if len(hits) >= max_hits:
                        break
            if len(hits) >= max_hits:
                break
        if len(hits) >= max_hits:
            break

    ev: list[EvidenceItem] = []
    if hits:
        ev.append(
            EvidenceItem(
                type="possible_secret_hits",
                ok=False,
                data={
                    "count": len(hits),
                    "samples": hits[:50],
                    "note": "仅输出规则名+文件+行号，不输出原始命中内容。",
                },
            )
        )
    else:
        ev.append(EvidenceItem(type="possible_secret_hits", ok=True, data={"count": 0}))
    return ev


def _redact_evidence_items(evidence: list[EvidenceItem]) -> list[EvidenceItem]:
    """对证据进行最小披露脱敏（用于共享 report/findings 时）。"""

    redacted: list[EvidenceItem] = []
    for e in evidence:
        if e.data and isinstance(e.data, dict) and "samples" in e.data and isinstance(e.data["samples"], list):
            samples = []
            for s in e.data["samples"]:
                if isinstance(s, dict) and "path" in s:
                    s2 = dict(s)
                    s2["path"] = "<redacted>"
                    samples.append(s2)
                else:
                    samples.append(s)
            d2 = dict(e.data)
            d2["samples"] = samples
            redacted.append(dataclasses.replace(e, data=d2))
        else:
            redacted.append(e)
    return redacted


def redact_findings(findings: list[Finding]) -> list[Finding]:
    """对 findings 做脱敏副本（目前仅脱敏 secret hit samples 的 path）。"""

    out: list[Finding] = []
    for f in findings:
        out.append(
            Finding(
                id=f.id,
                title=f.title,
                severity=f.severity,
                category=f.category,
                summary=f.summary,
                rule_sources=f.rule_sources,
                evidence=_redact_evidence_items(f.evidence),
                proposed_fix=f.proposed_fix,
                safe_to_autofix=f.safe_to_autofix,
                tags=f.tags,
                meta=f.meta,
            )
        )
    return out


def build_report_markdown(meta: dict[str, Any], findings: list[Finding]) -> str:
    """生成 report.md 内容。"""

    def sort_key(f: Finding) -> tuple[int, str]:
        order = {"high": 0, "medium": 1, "low": 2, "info": 3}
        return (order.get(f.severity, 9), f.id)

    counts: dict[str, int] = {"high": 0, "medium": 0, "low": 0, "info": 0}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1

    lines: list[str] = []
    lines.append("# Repo Compliance Audit Report")
    lines.append("")
    lines.append(f"- 生成时间（UTC）：{meta['generated_at']}")
    lines.append(f"- 仓库根目录：`{meta['repo_root']}`")
    if meta.get("git", {}).get("is_git_repo"):
        git = meta["git"]
        lines.append(f"- git：head=`{git.get('head')}` dirty={git.get('dirty')}")
    lines.append("")
    lines.append("## 摘要")
    lines.append("")
    lines.append(
        "- severity 计数："
        + ", ".join(f"{k}={v}" for k, v in counts.items())
    )
    lines.append("")
    lines.append("## Findings（按严重程度排序）")
    lines.append("")

    for f in sorted(findings, key=sort_key):
        lines.append(f"### {f.id} — {f.title}")
        lines.append("")
        lines.append(f"- severity: `{f.severity}`")
        lines.append(f"- category: `{f.category}`")
        lines.append(f"- safe_to_autofix: `{str(f.safe_to_autofix).lower()}`")
        if f.rule_sources:
            lines.append("- rule_sources:")
            for rs in f.rule_sources:
                lines.append(f"  - {rs}")
        lines.append(f"- summary: {f.summary}")
        lines.append("")
        lines.append("- evidence:")
        for e in f.evidence:
            if e.type == "path_exists":
                lines.append(f"  - path_exists `{e.path}` ok={e.ok}")
            elif e.data is not None:
                lines.append(f"  - {e.type}: {json.dumps(e.data, ensure_ascii=False)}")
            else:
                lines.append(f"  - {e.type}: ok={e.ok} {e.message or ''}".strip())
        if f.proposed_fix is not None:
            lines.append("")
            lines.append("- proposed_fix:")
            lines.append(f"  - kind: `{f.proposed_fix.kind}`")
            if f.proposed_fix.path:
                lines.append(f"  - path: `{f.proposed_fix.path}`")
            if f.proposed_fix.notes:
                lines.append(f"  - notes: {f.proposed_fix.notes}")
        lines.append("")

    lines.append("## 下一步（建议）")
    lines.append("")
    lines.append("1) 人类复核 high/medium findings（尤其是 POSSIBLE_SECRET_FOUND）。")
    lines.append("2) 选择需要整改的 `finding.id`，再运行 remediation 脚本。")
    lines.append("")
    return "\n".join(lines)


def write_outputs(out_dir: Path, report_md: str, payload: dict[str, Any]) -> tuple[Path, Path]:
    """写入 report.md 与 findings.json，并返回路径。"""

    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "report.md"
    findings_path = out_dir / "findings.json"
    report_path.write_text(report_md, encoding="utf-8")
    findings_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_path, findings_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析 CLI 参数。"""

    p = argparse.ArgumentParser(description="Repo compliance audit (read-only).")
    p.add_argument("--repo", type=str, default=".", help="目标仓库路径（默认当前目录）")
    p.add_argument(
        "--out",
        type=str,
        default="/tmp/repo-compliance-audit",
        help="输出目录（默认 /tmp/repo-compliance-audit）",
    )
    p.add_argument(
        "--fail-on",
        type=str,
        default="",
        help="当发现达到该 severity 时返回非 0（可选：high|medium|low|info）",
    )
    p.add_argument(
        "--redact",
        type=str,
        default="none",
        choices=["none", "report", "all"],
        help="输出脱敏模式：none（默认）/report（仅 report.md 脱敏）/all（report+findings.json 脱敏）",
    )
    p.add_argument(
        "--no-git-meta",
        action="store_true",
        help="不收集 git 元信息（减少泄露与噪声；仍可能使用 git 解析 repo root）",
    )
    p.add_argument(
        "--no-secret-scan",
        action="store_true",
        help="禁用疑似密钥扫描（减少误报/性能开销/报告风险）",
    )
    return p.parse_args(argv)


def should_fail(findings: list[Finding], fail_on: str) -> bool:
    """根据 fail_on 决定是否退出非 0。"""

    if not fail_on:
        return False
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    if fail_on not in order:
        return False
    threshold = order[fail_on]
    for f in findings:
        if order.get(f.severity, 99) <= threshold:
            return True
    return False


def main(argv: list[str]) -> int:
    """主流程入口。"""

    args = parse_args(argv)
    repo_root = resolve_repo_root(Path(args.repo))
    redact_mode: RedactMode = str(args.redact)

    if bool(args.no_git_meta):
        git_meta: dict[str, Any] = {"is_git_repo": False, "disabled": True}
    else:
        git_meta = collect_git_meta(repo_root)
        if redact_mode == "all" and git_meta.get("is_git_repo"):
            # changed_files 对外共享时可能泄露路径/结构
            git_meta = dict(git_meta)
            git_meta["changed_files"] = []

    rule_sources: list[str] = []
    required_paths: set[str] = set()
    agents_text = ""
    findings: list[Finding] = []

    # 规则文件完整性审查（优先执行）
    findings.extend(check_agents_integrity(repo_root, rule_sources=rule_sources))

    agents_path = repo_root / "AGENTS.md"
    if agents_path.exists():
        rule_sources.append("AGENTS.md（仓库规则）")
        agents_text = _read_text_best_effort(agents_path)
        if agents_text:
            required_paths = extract_agents_required_paths(agents_text)

    # docs / repro basics
    # （即使缺少 AGENTS，也可执行这些通用检查）

    docs_index = check_docs_index(repo_root, rule_sources=rule_sources)
    if docs_index is not None:
        findings.append(docs_index)

    worklog = check_worklog(repo_root, rule_sources=rule_sources)
    if worklog is not None:
        findings.append(worklog)

    env_example = check_env_example(repo_root, rule_sources=rule_sources)
    if env_example is not None:
        findings.append(env_example)

    # Spec-first（仅当有规则文件时更有意义）
    if agents_text:
        findings.extend(check_spec_entrypoint_and_sections(repo_root, rule_sources=rule_sources))

        tdd = check_tdd_evidence(repo_root, rule_sources=rule_sources)
        if tdd is not None:
            findings.append(tdd)

        lang = check_chinese_doc_language(repo_root, agents_text, rule_sources=rule_sources)
        if lang is not None:
            findings.append(lang)

        # “执行过程是否对齐规则”的即时取证（工作区有变更时才产出）
        findings.extend(check_agents_execution_evidence(repo_root, agents_text, rule_sources=rule_sources))

    # required paths（来自规则文件的动态要求；默认不自动修复）
    known_paths_with_dedicated_findings = {
        "DOCS_INDEX.md",
        "docs/worklog.md",
        ".env.example",
    }
    for rel in sorted(required_paths):
        if not _looks_like_repo_path(rel):
            continue
        if rel in known_paths_with_dedicated_findings:
            continue
        if (repo_root / rel).exists():
            continue

        _ensure_finding(
            findings,
            id="REQUIRED_PATH_MISSING",
            title=f"规则要求的路径缺失：{rel}",
            severity="medium",
            category="instruction",
            summary="规则文件中声明/暗示该路径应存在，但当前仓库缺失。",
            rule_sources=["AGENTS.md（自动提取）"],
            evidence=[_path_exists_evidence(repo_root, rel)],
            proposed_fix=ProposedFix(
                kind="manual_or_repo_specific",
                path=rel,
                notes="该项通常依赖仓库约定，默认不自动创建；建议人工确认后再整改。",
            ),
            safe_to_autofix=False,
            tags=["instruction", "rules"],
            meta={"required_path": rel},
        )

    # secrets scan（可禁用）
    if not bool(args.no_secret_scan):
        secret_evidence = scan_possible_secrets(repo_root)
        if secret_evidence and secret_evidence[0].ok is False:
            _ensure_finding(
                findings,
                id="POSSIBLE_SECRET_FOUND",
                title="发现疑似密钥/私钥/令牌",
                severity="high",
                category="security",
                summary="扫描到疑似敏感信息命中。需要人工复核并按安全流程处理（撤销/轮转/清理历史）。",
                rule_sources=["敏感信息扫描（启发式）"],
                evidence=secret_evidence,
                proposed_fix=ProposedFix(
                    kind="manual_required",
                    notes="强制人工处理：确认 → 轮转/撤销 → 清理历史 → 加强 .gitignore / 预提交钩子。",
                ),
                safe_to_autofix=False,
                tags=["secret", "security"],
                meta={},
            )

    payload = {
        "meta": {
            "tool": "repo-compliance-audit",
            "version": VERSION,
            "generated_at": _utc_now_iso(),
            "repo_root": str(repo_root) if redact_mode != "all" else "<redacted>",
            "git": git_meta,
        },
        "summary": {
            "counts_by_severity": {},
            "counts_by_category": {},
        },
        "findings": [f.to_dict() for f in findings],
    }

    for f in findings:
        payload["summary"]["counts_by_severity"][f.severity] = (
            payload["summary"]["counts_by_severity"].get(f.severity, 0) + 1
        )
        payload["summary"]["counts_by_category"][f.category] = (
            payload["summary"]["counts_by_category"].get(f.category, 0) + 1
        )

    report_repo_root = "<redacted>" if redact_mode in {"report", "all"} else str(repo_root)
    report_findings = redact_findings(findings) if redact_mode in {"report", "all"} else findings

    report_md = build_report_markdown(
        {"generated_at": payload["meta"]["generated_at"], "repo_root": report_repo_root, "git": git_meta},
        report_findings,
    )

    if redact_mode == "all":
        # findings.json 也脱敏（仅做最小披露：secret samples 的 path）
        payload["findings"] = [f.to_dict() for f in redact_findings(findings)]

    out_dir = Path(args.out).expanduser().resolve()
    report_path, findings_path = write_outputs(out_dir, report_md, payload)

    print(f"[repo-compliance-audit] report: {report_path}")
    print(f"[repo-compliance-audit] findings: {findings_path}")

    if should_fail(findings, str(args.fail_on).strip()):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
