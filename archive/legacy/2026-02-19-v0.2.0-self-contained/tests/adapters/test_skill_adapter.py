from __future__ import annotations

import pytest

from capability_runtime.adapters.skill_adapter import SkillAdapter
from capability_runtime.protocol.capability import (
    CapabilityKind,
    CapabilityRef,
    CapabilitySpec,
    CapabilityStatus,
)
from capability_runtime.protocol.context import ExecutionContext
from capability_runtime.protocol.skill import SkillDispatchRule, SkillSpec


class FakeRuntime:
    def __init__(self, *, workspace_root: str, skill_uri_allowlist: list[str] | None = None) -> None:
        class Cfg:
            def __init__(self, root: str, allowlist: list[str]) -> None:
                self.workspace_root = root
                self.skill_uri_allowlist = allowlist

        self.config = Cfg(workspace_root, skill_uri_allowlist or [])
        self.called: list[str] = []

    async def _execute(self, *, capability_id: str, input: dict, context: ExecutionContext):
        self.called.append(capability_id)
        from capability_runtime.protocol.capability import CapabilityResult

        return CapabilityResult(status=CapabilityStatus.SUCCESS, output={"id": capability_id})


@pytest.mark.asyncio
async def test_skill_inline_loads_content(tmp_path) -> None:
    rt = FakeRuntime(workspace_root=str(tmp_path))
    adapter = SkillAdapter()
    spec = SkillSpec(base=CapabilitySpec(id="s", kind=CapabilityKind.SKILL, name="S"), source="hello", source_type="inline")
    res = await adapter.execute(spec=spec, input={}, context=ExecutionContext(run_id="r"), runtime=rt)
    assert res.output == "hello"


@pytest.mark.asyncio
async def test_skill_file_loads_content(tmp_path) -> None:
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "a.md").write_text("A", encoding="utf-8")
    rt = FakeRuntime(workspace_root=str(tmp_path))
    adapter = SkillAdapter()
    spec = SkillSpec(base=CapabilitySpec(id="s", kind=CapabilityKind.SKILL, name="S"), source="skills/a.md", source_type="file")
    res = await adapter.execute(spec=spec, input={}, context=ExecutionContext(run_id="r"), runtime=rt)
    assert res.output == "A"


@pytest.mark.asyncio
async def test_skill_dispatch_rules_priority_and_condition(tmp_path) -> None:
    rt = FakeRuntime(workspace_root=str(tmp_path))
    adapter = SkillAdapter()
    spec = SkillSpec(
        base=CapabilitySpec(id="s", kind=CapabilityKind.SKILL, name="S"),
        source="ignored",
        source_type="inline",
        dispatch_rules=[
            SkillDispatchRule(condition="missing", target=CapabilityRef(id="cap-low"), priority=1),
            SkillDispatchRule(condition="flag", target=CapabilityRef(id="cap-high"), priority=10),
        ],
    )
    ctx = ExecutionContext(run_id="r", bag={"flag": True})
    res = await adapter.execute(spec=spec, input={"x": 1}, context=ctx, runtime=rt)
    assert res.status == CapabilityStatus.SUCCESS
    assert rt.called == ["cap-high"]


@pytest.mark.asyncio
async def test_skill_uri_disabled_by_default_without_network(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked_urlopen(*_args, **_kwargs):
        raise AssertionError("urlopen should not be called when uri source is not allowlisted")

    monkeypatch.setattr("capability_runtime.adapters.skill_adapter.urlopen", _blocked_urlopen)

    rt = FakeRuntime(workspace_root=str(tmp_path))
    adapter = SkillAdapter()
    spec = SkillSpec(
        base=CapabilitySpec(id="s", kind=CapabilityKind.SKILL, name="S"),
        source="https://example.com/skill.md",
        source_type="uri",
    )

    res = await adapter.execute(spec=spec, input={}, context=ExecutionContext(run_id="r"), runtime=rt)
    assert res.status == CapabilityStatus.FAILED
    assert res.error is not None
    assert "allowlist" in res.error


@pytest.mark.asyncio
async def test_skill_uri_allowed_when_prefix_matches_allowlist(tmp_path) -> None:
    skill_file = tmp_path / "skill.txt"
    skill_file.write_text("URI SKILL", encoding="utf-8")
    uri = skill_file.resolve().as_uri()

    rt = FakeRuntime(workspace_root=str(tmp_path), skill_uri_allowlist=["file://"])
    adapter = SkillAdapter()
    spec = SkillSpec(base=CapabilitySpec(id="s", kind=CapabilityKind.SKILL, name="S"), source=uri, source_type="uri")

    res = await adapter.execute(spec=spec, input={}, context=ExecutionContext(run_id="r"), runtime=rt)
    assert res.status == CapabilityStatus.SUCCESS
    assert res.output == "URI SKILL"
