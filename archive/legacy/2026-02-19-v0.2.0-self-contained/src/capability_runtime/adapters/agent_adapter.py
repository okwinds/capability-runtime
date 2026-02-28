"""
adapters/agent_adapter.py

AgentAdapter：桥接 Agent 元能力。

本仓库 v0.2.0 阶段的关键目标是“能力协议 + 执行引擎 + 可回归的编排”，
因此这里提供一个可测试的 adapter 结构：支持注入 runner 以离线回归。

生产环境若需真实 LLM/上游 Agent SDK 执行，应由宿主提供 runner 或在后续迭代补齐默认 runner。
"""

from __future__ import annotations

from typing import Any, Awaitable, Protocol

from ..protocol.agent import AgentSpec
from ..protocol.capability import CapabilityKind
from ..protocol.capability import CapabilityResult, CapabilityStatus
from ..protocol.context import ExecutionContext
from ..protocol.skill import SkillSpec
from .skill_adapter import SkillAdapter


class AgentRunner(Protocol):
    """
    Agent 执行器协议（用于离线测试注入）。

    返回：
    - CapabilityResult
    """

    async def __call__(
        self,
        *,
        spec: AgentSpec,
        input: dict[str, Any],
        skills_text: str,
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """执行 Agent 并返回 CapabilityResult。"""


class AgentAdapter:
    """
    AgentAdapter：把 AgentSpec 转为实际执行。

    本实现优先保证：
    - 可注入 runner 做离线回归
    - skills 注入策略可回归（SkillAdapter.load_for_injection）
    """

    def __init__(self, *, skill_adapter: SkillAdapter, runner: AgentRunner | None = None) -> None:
        """
        创建 AgentAdapter。

        参数：
        - skill_adapter：SkillAdapter
        - runner：可选执行器（推荐在测试/离线场景提供）
        """

        self._skill_adapter = skill_adapter
        self._runner = runner

    async def execute(  # noqa: PLR0913 - 参数显式化是契约的一部分
        self,
        *,
        spec: AgentSpec,
        input: dict[str, Any],
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """
        执行 Agent。

        行为（最小实现）：
        1) 计算要注入的 skill id 列表：
           - 显式：spec.skills
           - 自动：扫描所有 SkillSpec，若当前 agent_id 命中 skill.inject_to，则自动注入
           - 去重：保持显式 skills 的顺序优先
        2) 从 runtime.registry 取 SkillSpec，并加载为注入文本；
        3) 拼接成 skills_text；
        4) 委托 runner 执行（若未提供 runner，返回 FAILED）。
        """

        skill_ids: list[str] = list(spec.skills)
        agent_id = spec.base.id
        for maybe_skill in runtime.registry.list_by_kind(CapabilityKind.SKILL):
            if not isinstance(maybe_skill, SkillSpec):
                continue
            if agent_id in (maybe_skill.inject_to or []):
                skill_ids.append(maybe_skill.base.id)

        deduped: list[str] = []
        seen: set[str] = set()
        for sid in skill_ids:
            if sid in seen:
                continue
            seen.add(sid)
            deduped.append(sid)

        skills_texts: list[str] = []
        for sid in deduped:
            s = runtime.registry.get(sid)
            if s is None:
                return CapabilityResult(status=CapabilityStatus.FAILED, error=f"missing skill for injection: {sid}")
            if not isinstance(s, SkillSpec):
                return CapabilityResult(status=CapabilityStatus.FAILED, error=f"skill id is not SkillSpec: {sid}")
            skills_texts.append(self._skill_adapter.load_for_injection(spec=s, runtime=runtime))

        skills_text = "\n\n".join([t for t in skills_texts if t.strip()])

        if self._runner is None:
            return CapabilityResult(status=CapabilityStatus.FAILED, error="AgentAdapter runner is not configured")

        return await self._runner(spec=spec, input=input, skills_text=skills_text, context=context, runtime=runtime)
