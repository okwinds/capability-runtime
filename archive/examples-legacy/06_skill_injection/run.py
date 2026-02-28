"""示例 06（已迁移）：skills 注入不再由本仓 Protocol 提供（方案2）。"""

from __future__ import annotations


def main() -> None:
    """
    说明：
    - 旧版示例基于 `SkillSpec.inject_to` + `SkillAdapter`（本仓自带 skills 原语）。
    - 方案2 已移除 Skill 原语：skills 的发现/mention/sources/preflight/tools/approvals/WAL
      全部以 `skills-runtime-sdk-python`（模块 `agent_sdk`）为真相源。

    迁移建议（最小思路）：
    1) 在 SDK 配置（YAML overlays）中声明 Strict Catalog + sources；
    2) 在 task/prompt 中使用 strict mention 直接引用 skills；
    3) 通过本仓 `Runtime.preflight()` / `preflight_or_raise()` 做 gate；
    4) 通过 NodeReport/WAL 证据链做编排与审计。
    """

    print("=== 06_skill_injection（已迁移） ===")
    print("本仓已移除 `SkillSpec.inject_to` / `SkillAdapter`（方案2）。")
    print("请改用 `agent_sdk` 的 skills 引擎（Strict Catalog + strict mention + overlays）。")
    print()
    print("参考：")
    print("- `docs/internal/specs/engineering-spec/02_Technical_Design/SKILLS_SYSTEM.md`")
    print("- `docs/internal/specs/engineering-spec/02_Technical_Design/SKILLS_PREFLIGHT.md`")
    print("- `docs/internal/specs/engineering-spec/04_Operations/CONFIGURATION.md`")


if __name__ == "__main__":
    main()

