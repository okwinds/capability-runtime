from __future__ import annotations

from pathlib import Path

import pytest

from skills_runtime.core.errors import FrameworkError
from skills_runtime.skills.manager import SkillsManager
from skills_runtime.skills.mentions import extract_skill_mentions
from skills_runtime.tools.builtin.skill_exec import _parse_single_skill_mention as _parse_single_skill_mention_exec
from skills_runtime.tools.builtin.skill_exec import skill_exec
from skills_runtime.tools.builtin.skill_ref_read import _parse_single_skill_mention as _parse_single_skill_mention_ref
from skills_runtime.tools.builtin.skill_ref_read import skill_ref_read
from skills_runtime.tools.protocol import ToolCall
from skills_runtime.tools.registry import ToolExecutionContext


def _write_minimal_skill_md(path: Path, *, name: str = "hello_skill", description: str = "desc") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                "---",
                "",
                "body",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _mk_manager(*, workspace_root: Path, skills_root: str, refresh_policy: str = "ttl") -> SkillsManager:
    return SkillsManager(
        workspace_root=workspace_root,
        skills_config={
            # strictness 默认值由 SDK 负责；桥接层只做“不要绕过/不要破坏”的冒烟。
            "spaces": [
                {
                    "id": "space-1",
                    "account": "alice",
                    "domain": "engineering",
                    "sources": ["src-fs"],
                    "enabled": True,
                }
            ],
            "sources": [{"id": "src-fs", "type": "filesystem", "options": {"root": skills_root}}],
            "scan": {"refresh_policy": refresh_policy, "ttl_sec": 60, "max_frontmatter_bytes": 16384, "max_depth": 4},
        },
    )


def test_b001_free_text_mention_extract_only():
    text = (
        "prefix $[alice:engineering].hello_skill middle "
        "$name legacy "
        "$[alice:engineering].hello_skill]typo "
        "suffix"
    )
    mentions = extract_skill_mentions(text)
    assert [(m.account, m.domain, m.skill_name, m.mention_text) for m in mentions] == [
        ("alice", "engineering", "hello_skill", "$[alice:engineering].hello_skill")
    ]


@pytest.mark.parametrize(
    "raw",
    [
        "$[aa:bb].xx then do",
        "text $[aa:bb].xx text",
        "$name",
        "",
        "   ",
    ],
)
def test_b002_tool_args_skill_mention_must_be_single_full_token(raw: str):
    with pytest.raises(FrameworkError) as ei:
        _parse_single_skill_mention_exec(raw)
    assert ei.value.code == "SKILL_MENTION_FORMAT_INVALID"
    assert isinstance(ei.value.details, dict)
    assert ei.value.details.get("reason")

    with pytest.raises(FrameworkError) as ei2:
        _parse_single_skill_mention_ref(raw)
    assert ei2.value.code == "SKILL_MENTION_FORMAT_INVALID"


def test_b002_tool_args_skill_mention_single_token_ok():
    mention = _parse_single_skill_mention_exec("$[aa:bb].xx")
    assert mention.account == "aa"
    assert mention.domain == "bb"
    assert mention.skill_name == "xx"


def test_b004_refresh_policy_ttl_refresh_failed_fallback_to_cached_ok(tmp_path: Path):
    # 初次 scan 成功，建立 cached_ok。
    mgr = _mk_manager(workspace_root=tmp_path, skills_root="./skills", refresh_policy="ttl")
    _write_minimal_skill_md(tmp_path / "skills" / "s1" / "SKILL.md", name="hello_skill", description="d")
    r1 = mgr.scan()
    assert not r1.errors
    assert [s.skill_name for s in r1.skills] == ["hello_skill"]

    # 再次 refresh：用“无效元数据”制造 scan_errors，触发 refresh_failed fallback。
    (tmp_path / "skills" / "s1" / "SKILL.md").write_text("---\ndescription: missing name\n---\n", encoding="utf-8")
    r2 = mgr.refresh()
    assert not r2.errors
    assert [s.skill_name for s in r2.skills] == ["hello_skill"]  # 回退到旧缓存
    assert any(w.code == "SKILL_SCAN_REFRESH_FAILED" for w in r2.warnings)
    warn = next(w for w in r2.warnings if w.code == "SKILL_SCAN_REFRESH_FAILED")
    assert warn.details.get("refresh_policy") == "ttl"
    assert warn.details.get("reason")


def test_b005_scan_frontmatter_only_does_not_load_skill_body(tmp_path: Path, monkeypatch):
    mgr = _mk_manager(workspace_root=tmp_path, skills_root="./skills", refresh_policy="manual")
    _write_minimal_skill_md(tmp_path / "skills" / "s1" / "SKILL.md", name="hello_skill", description="d")

    # scan 阶段必须 metadata-only：不允许走 load_skill_from_path（会读取全文并解析 body）。
    import skills_runtime.skills.loader as loader

    def _boom(*args, **kwargs):
        raise AssertionError("scan must not call load_skill_from_path (body load)")

    monkeypatch.setattr(loader, "load_skill_from_path", _boom)

    report = mgr.scan()
    assert not report.errors
    assert [s.skill_name for s in report.skills] == ["hello_skill"]


def _tool_ctx(*, workspace_root: Path, skills_manager: SkillsManager | None = None) -> ToolExecutionContext:
    return ToolExecutionContext(workspace_root=workspace_root, run_id="r1", skills_manager=skills_manager)


def test_b006_skill_exec_disabled_returns_expected_code(tmp_path: Path):
    call = ToolCall(call_id="c1", name="skill_exec", args={"skill_mention": "$[aa:bb].xx", "action_id": "a"})
    res = skill_exec(call, _tool_ctx(workspace_root=tmp_path, skills_manager=None))
    assert res.ok is False
    assert res.details["data"]["error"]["code"] == "SKILL_ACTIONS_DISABLED"


def test_b006_skill_ref_read_disabled_returns_expected_code(tmp_path: Path):
    call = ToolCall(
        call_id="c1",
        name="skill_ref_read",
        args={"skill_mention": "$[aa:bb].xx", "ref_path": "references/a.md"},
    )
    res = skill_ref_read(call, _tool_ctx(workspace_root=tmp_path, skills_manager=None))
    assert res.ok is False
    assert res.details["data"]["error"]["code"] == "SKILL_REFERENCES_DISABLED"
