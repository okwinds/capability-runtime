"""SkillAdapter 单元测试。"""
from __future__ import annotations

import pytest

from agently_skills_runtime.adapters.skill_adapter import SkillAdapter
from agently_skills_runtime.protocol.agent import AgentSpec
from agently_skills_runtime.protocol.capability import (
    CapabilityKind,
    CapabilityRef,
    CapabilityResult,
    CapabilitySpec,
    CapabilityStatus,
)
from agently_skills_runtime.protocol.context import ExecutionContext
from agently_skills_runtime.protocol.skill import SkillDispatchRule, SkillSpec
from agently_skills_runtime.runtime.engine import CapabilityRuntime


@pytest.mark.asyncio
async def test_inline_skill():
    spec = SkillSpec(
        base=CapabilitySpec(id="s1", kind=CapabilityKind.SKILL, name="inline"),
        source="这是内联内容",
        source_type="inline",
    )
    adapter = SkillAdapter()
    rt = CapabilityRuntime()
    ctx = ExecutionContext(run_id="r1")

    result = await adapter.execute(spec=spec, input={}, context=ctx, runtime=rt)
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output == "这是内联内容"


@pytest.mark.asyncio
async def test_file_skill(tmp_path):
    skill_file = tmp_path / "skill.md"
    skill_file.write_text("# Skill 内容\n文件加载成功", encoding="utf-8")

    spec = SkillSpec(
        base=CapabilitySpec(id="s2", kind=CapabilityKind.SKILL, name="file"),
        source="skill.md",
        source_type="file",
    )
    adapter = SkillAdapter(workspace_root=str(tmp_path))
    rt = CapabilityRuntime()
    ctx = ExecutionContext(run_id="r1")

    result = await adapter.execute(spec=spec, input={}, context=ctx, runtime=rt)
    assert result.status == CapabilityStatus.SUCCESS
    assert "文件加载成功" in result.output


@pytest.mark.asyncio
async def test_uri_skill_blocked():
    spec = SkillSpec(
        base=CapabilitySpec(id="s3", kind=CapabilityKind.SKILL, name="uri"),
        source="https://example.com/skill",
        source_type="uri",
    )
    adapter = SkillAdapter()
    rt = CapabilityRuntime()
    ctx = ExecutionContext(run_id="r1")

    result = await adapter.execute(spec=spec, input={}, context=ctx, runtime=rt)
    assert result.status == CapabilityStatus.FAILED
    assert "allowlist" in (result.error or "").lower() or "uri" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_file_skill_path_traversal_blocked(tmp_path):
    workspace_root = tmp_path / "root"
    workspace_root.mkdir()
    (workspace_root / "ok.md").write_text("ok", encoding="utf-8")

    secret = tmp_path / "secret.txt"
    secret.write_text("do not read", encoding="utf-8")

    spec = SkillSpec(
        base=CapabilitySpec(id="s_path", kind=CapabilityKind.SKILL, name="file_escape"),
        source="../secret.txt",
        source_type="file",
    )
    adapter = SkillAdapter(workspace_root=str(workspace_root))
    rt = CapabilityRuntime()
    ctx = ExecutionContext(run_id="r1")

    result = await adapter.execute(spec=spec, input={}, context=ctx, runtime=rt)
    assert result.status == CapabilityStatus.FAILED


@pytest.mark.asyncio
async def test_uri_skill_file_allowed(tmp_path):
    skill_file = tmp_path / "skill.md"
    skill_file.write_text("file uri ok", encoding="utf-8")

    uri = skill_file.resolve().as_uri()
    allow_prefix = tmp_path.resolve().as_uri().rstrip("/") + "/"

    spec = SkillSpec(
        base=CapabilitySpec(id="s_file", kind=CapabilityKind.SKILL, name="uri_file"),
        source=uri,
        source_type="uri",
    )
    adapter = SkillAdapter(uri_allowlist=[allow_prefix])
    rt = CapabilityRuntime()
    ctx = ExecutionContext(run_id="r1")

    result = await adapter.execute(spec=spec, input={}, context=ctx, runtime=rt)
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output == "file uri ok"


@pytest.mark.asyncio
async def test_uri_skill_https_allowed_via_injected_fetcher():
    calls = []

    def fetcher(uri: str, *, max_bytes: int) -> str:
        calls.append({"uri": uri, "max_bytes": max_bytes})
        return "https uri ok"

    spec = SkillSpec(
        base=CapabilitySpec(id="s_https", kind=CapabilityKind.SKILL, name="uri_https"),
        source="https://example.com/skills/s1.md",
        source_type="uri",
    )
    adapter = SkillAdapter(uri_allowlist=["https://example.com/skills/"], uri_fetcher=fetcher)
    rt = CapabilityRuntime()
    ctx = ExecutionContext(run_id="r1")

    result = await adapter.execute(spec=spec, input={}, context=ctx, runtime=rt)
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output == "https uri ok"
    assert calls and calls[0]["uri"] == "https://example.com/skills/s1.md"


@pytest.mark.asyncio
async def test_uri_skill_scheme_not_allowed():
    spec = SkillSpec(
        base=CapabilitySpec(id="s_ftp", kind=CapabilityKind.SKILL, name="uri_ftp"),
        source="ftp://example.com/skill",
        source_type="uri",
    )
    adapter = SkillAdapter(uri_allowlist=["ftp://example.com/"])
    rt = CapabilityRuntime()
    ctx = ExecutionContext(run_id="r1")

    result = await adapter.execute(spec=spec, input={}, context=ctx, runtime=rt)
    assert result.status == CapabilityStatus.FAILED


@pytest.mark.asyncio
async def test_dispatch_rule_triggered():
    """dispatch_rule 触发时调用目标能力。"""

    class EchoAdapter:
        async def execute(self, *, spec, input, context, runtime):
            return CapabilityResult(
                status=CapabilityStatus.SUCCESS,
                output=f"dispatched to {spec.base.id}",
            )

    skill = SkillSpec(
        base=CapabilitySpec(id="s1", kind=CapabilityKind.SKILL, name="s1"),
        source="content",
        source_type="inline",
        dispatch_rules=[
            SkillDispatchRule(condition="trigger_flag", target=CapabilityRef(id="A")),
        ],
    )
    agent = AgentSpec(
        base=CapabilitySpec(id="A", kind=CapabilityKind.AGENT, name="A"),
    )

    rt = CapabilityRuntime()
    rt.set_adapter(CapabilityKind.AGENT, EchoAdapter())
    rt.set_adapter(CapabilityKind.SKILL, SkillAdapter())
    rt.registry.register(skill)
    rt.registry.register(agent)

    # trigger_flag 为 True
    ctx = ExecutionContext(run_id="r1", bag={"trigger_flag": True})
    result = await SkillAdapter().execute(spec=skill, input={}, context=ctx, runtime=rt)
    assert result.status == CapabilityStatus.SUCCESS
    assert result.output == "content"
    assert len(result.metadata.get("dispatched", [])) == 1

    # trigger_flag 为 False
    ctx2 = ExecutionContext(run_id="r2", bag={"trigger_flag": False})
    result2 = await SkillAdapter().execute(
        spec=skill, input={}, context=ctx2, runtime=rt
    )
    assert result2.metadata.get("dispatched") is None or len(
        result2.metadata.get("dispatched", [])
    ) == 0


@pytest.mark.asyncio
async def test_dispatch_rule_priority_is_applied():
    """当多个规则同时命中时，应按 priority（desc）稳定执行。"""

    class EchoAdapter:
        async def execute(self, *, spec, input, context, runtime):
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output=spec.base.id)

    skill = SkillSpec(
        base=CapabilitySpec(id="s_pri", kind=CapabilityKind.SKILL, name="s_pri"),
        source="content",
        source_type="inline",
        dispatch_rules=[
            SkillDispatchRule(condition="trigger", target=CapabilityRef(id="LOW"), priority=1),
            SkillDispatchRule(condition="trigger", target=CapabilityRef(id="HIGH"), priority=10),
        ],
    )
    low = AgentSpec(base=CapabilitySpec(id="LOW", kind=CapabilityKind.AGENT, name="LOW"))
    high = AgentSpec(base=CapabilitySpec(id="HIGH", kind=CapabilityKind.AGENT, name="HIGH"))

    rt = CapabilityRuntime()
    rt.set_adapter(CapabilityKind.AGENT, EchoAdapter())
    rt.set_adapter(CapabilityKind.SKILL, SkillAdapter())
    rt.registry.register(skill)
    rt.registry.register(low)
    rt.registry.register(high)

    ctx = ExecutionContext(run_id="r1", bag={"trigger": True})
    result = await SkillAdapter().execute(spec=skill, input={}, context=ctx, runtime=rt)
    dispatched = result.metadata.get("dispatched", [])
    assert [d.get("target") for d in dispatched] == ["HIGH", "LOW"]
