"""
adapters/skill_adapter.py

SkillAdapter：桥接 Skill 元能力（内容加载 + 可选调度规则 dispatch_rules）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from ..protocol.capability import CapabilityResult, CapabilityStatus
from ..protocol.context import ExecutionContext
from ..protocol.skill import SkillSpec


@dataclass(frozen=True)
class LoadedSkill:
    """
    已加载的 Skill 内容。

    参数：
    - spec_id：Skill ID
    - content：技能内容文本
    """

    spec_id: str
    content: str


class SkillAdapter:
    """
    SkillAdapter：负责加载 Skill 内容，并在满足 dispatch_rules 时委托 runtime 执行目标能力。
    """

    async def execute(  # noqa: PLR0913 - 明确参数是契约的一部分
        self,
        *,
        spec: SkillSpec,
        input: dict[str, Any],
        context: ExecutionContext,
        runtime: Any,
    ) -> CapabilityResult:
        """
        执行 Skill。

        行为：
        - 若存在 dispatch_rules：按 priority（大者优先）评估 condition；匹配则委托 runtime._execute(target) 并返回其结果。
        - 否则：加载 Skill 内容并返回（output 为字符串）。

        参数：
        - spec：SkillSpec
        - input：输入 dict（透传给被调度的目标能力）
        - context：ExecutionContext
        - runtime：CapabilityRuntime（必须提供 `_execute()` 与 `config.workspace_root`）
        """

        try:
            if spec.dispatch_rules:
                rules = sorted(spec.dispatch_rules, key=lambda r: r.priority, reverse=True)
                for rule in rules:
                    if self._evaluate_condition(rule.condition, input=input, context=context):
                        return await runtime._execute(capability_id=rule.target.id, input=input, context=context)

            content = self._load_skill_content(
                spec=spec,
                workspace_root=Path(runtime.config.workspace_root),
                skill_uri_allowlist=list(runtime.config.skill_uri_allowlist),
            )
            return CapabilityResult(status=CapabilityStatus.SUCCESS, output=content)
        except Exception as exc:
            return CapabilityResult(status=CapabilityStatus.FAILED, error=f"{type(exc).__name__}: {exc}")

    def load_for_injection(self, *, spec: SkillSpec, runtime: Any) -> str:
        """
        加载 Skill 内容供注入 Agent（字符串）。

        参数：
        - spec：SkillSpec
        - runtime：CapabilityRuntime（用于 workspace_root）
        """

        return self._load_skill_content(
            spec=spec,
            workspace_root=Path(runtime.config.workspace_root),
            skill_uri_allowlist=list(runtime.config.skill_uri_allowlist),
        )

    def _evaluate_condition(self, condition: str, *, input: dict[str, Any], context: ExecutionContext) -> bool:
        """
        Phase 1 条件评估：最小实现（bag key 存在/为真 + resolve_mapping）。

        参数：
        - condition：条件字符串
        - input：输入 dict（预留；当前不解析）
        - context：ExecutionContext

        返回：
        - bool
        """

        cond = (condition or "").strip()
        if not cond:
            return False

        if any(cond.startswith(p) for p in ("context.", "previous.", "step.", "item", "literal.")):
            try:
                return bool(context.resolve_mapping(cond))
            except Exception:
                return False

        return bool(context.bag.get(cond))

    def _load_skill_content(self, *, spec: SkillSpec, workspace_root: Path, skill_uri_allowlist: list[str]) -> str:
        """
        按 source_type 加载 Skill 内容。

        参数：
        - spec：SkillSpec
        - workspace_root：工作区根目录（用于 file 相对路径）
        - skill_uri_allowlist：URI 前缀 allowlist（为空表示禁用 uri）

        返回：
        - 内容字符串
        """

        st = (spec.source_type or "file").strip().lower()
        if st == "inline":
            return spec.source
        if st == "file":
            path = (workspace_root / spec.source).expanduser().resolve()
            return path.read_text(encoding="utf-8")
        if st == "uri":
            if not self._is_uri_allowed(uri=spec.source, allowlist=skill_uri_allowlist):
                raise PermissionError(
                    "skill uri source is disabled by runtime policy "
                    f"(source={spec.source!r}). Set RuntimeConfig.skill_uri_allowlist to an allowed URI prefix."
                )
            with urlopen(spec.source, timeout=10) as fp:  # nosec - uri 由宿主控制；离线测试使用 file://
                raw = fp.read()
            return raw.decode("utf-8", errors="replace")

        raise ValueError(f"unknown source_type: {spec.source_type!r}")

    def _is_uri_allowed(self, *, uri: str, allowlist: list[str]) -> bool:
        """
        判断 URI 是否命中 allowlist。

        规则：
        - allowlist 为空：全部拒绝（安全默认）。
        - allowlist 任一前缀命中 uri.startswith(prefix)：允许。
        """

        if not allowlist:
            return False
        return any(uri.startswith(prefix) for prefix in allowlist)
