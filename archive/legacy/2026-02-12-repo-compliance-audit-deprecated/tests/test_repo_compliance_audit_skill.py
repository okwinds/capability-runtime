import json
import subprocess
import sys
import tempfile
from pathlib import Path
from shutil import which

import pytest


def test_audit_and_remediate_minimal_repo():
    with tempfile.TemporaryDirectory() as td:
        repo_root = Path(td)

        (repo_root / "AGENTS.md").write_text(
            "\n".join(
                [
                    "# AGENTS",
                    "",
                    "## 0.1) 文档与目录默认值（可按项目覆盖）",
                    "",
                    "- 文档索引：`DOCS_INDEX.md`",
                    "- 工作记录：`docs/worklog.md`",
                    "",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        (repo_root / ".env").write_text("API_KEY=supersecret\nDEBUG=true\n", encoding="utf-8")

        out_dir = repo_root / "_audit_out"
        audit_script = Path("skills/repo-compliance-audit/scripts/audit_repo.py").resolve()
        remediate_script = Path("skills/repo-compliance-audit/scripts/remediate_repo.py").resolve()

        p = subprocess.run(
            [sys.executable, str(audit_script), "--repo", str(repo_root), "--out", str(out_dir)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert "findings:" in p.stdout

        findings_path = out_dir / "findings.json"
        payload = json.loads(findings_path.read_text(encoding="utf-8"))
        ids = {f["id"] for f in payload["findings"]}

        assert "DOCS_INDEX_MISSING" in ids
        assert "WORKLOG_MISSING" in ids
        assert "ENV_EXAMPLE_MISSING" in ids

        subprocess.run(
            [
                sys.executable,
                str(remediate_script),
                "--repo",
                str(repo_root),
                "--findings",
                str(findings_path),
                "--select",
                "DOCS_INDEX_MISSING,ENV_EXAMPLE_MISSING",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        assert (repo_root / "DOCS_INDEX.md").exists()
        assert (repo_root / ".env.example").exists()

        env_example = (repo_root / ".env.example").read_text(encoding="utf-8")
        assert "API_KEY=" in env_example
        assert "DEBUG=" in env_example
        assert "supersecret" not in env_example


def test_audit_agents_instruction_findings():
    with tempfile.TemporaryDirectory() as td:
        repo_root = Path(td)

        (repo_root / "AGENTS.md").write_text(
            "\n".join(
                [
                    "# AGENTS",
                    "",
                    "1) 文档契约驱动（Doc/Spec First）",
                    "- Spec 至少包含：目标、约束、接口/事件协议、验收标准、测试计划",
                    "",
                    "2) 测试驱动交付（TDD as Gate）",
                    "- 功能完成的定义：相关测试通过，并记录到 worklog",
                    "",
                    "推荐默认值：",
                    "- 文档索引：`DOCS_INDEX.md`",
                    "- 工作记录：`docs/worklog.md`",
                    "",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        (repo_root / "DOCS_INDEX.md").write_text("# 文档索引\n", encoding="utf-8")
        (repo_root / "docs").mkdir(parents=True, exist_ok=True)
        (repo_root / "docs/worklog.md").write_text("# Worklog\n\n## 2026-02-06\n- no tests\n", encoding="utf-8")

        out_dir = repo_root / "_audit_out"
        audit_script = Path("skills/repo-compliance-audit/scripts/audit_repo.py").resolve()

        subprocess.run(
            [sys.executable, str(audit_script), "--repo", str(repo_root), "--out", str(out_dir)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        payload = json.loads((out_dir / "findings.json").read_text(encoding="utf-8"))
        ids = {f["id"] for f in payload["findings"]}
        assert "SPEC_ENTRYPOINT_MISSING" in ids
        assert "TDD_EVIDENCE_MISSING" in ids


def test_agents_modified_detected_when_git_available():
    if which("git") is None:
        pytest.skip("git not available")

    with tempfile.TemporaryDirectory() as td:
        repo_root = Path(td)
        audit_script = Path("skills/repo-compliance-audit/scripts/audit_repo.py").resolve()
        out_dir = repo_root / "_audit_out"

        def run_git(*args: str) -> None:
            subprocess.run(
                ["git", *args],
                cwd=str(repo_root),
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

        run_git("init")
        run_git("config", "user.email", "audit@example.com")
        run_git("config", "user.name", "audit")

        (repo_root / "AGENTS.md").write_text("# AGENTS\n- rule\n", encoding="utf-8")
        run_git("add", "AGENTS.md")
        run_git("commit", "-m", "add agents")

        (repo_root / "AGENTS.md").write_text("# AGENTS\n- rule\n- changed\n", encoding="utf-8")

        subprocess.run(
            [sys.executable, str(audit_script), "--repo", str(repo_root), "--out", str(out_dir), "--no-secret-scan"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        payload = json.loads((out_dir / "findings.json").read_text(encoding="utf-8"))
        ids = {f["id"] for f in payload["findings"]}
        assert "AGENTS_MD_MODIFIED" in ids
