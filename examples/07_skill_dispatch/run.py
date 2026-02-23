"""示例 07（已迁移）：dispatch_rules 不再由本仓 Protocol 提供（方案2）。"""

from __future__ import annotations


def main() -> None:
    """
    说明：
    - 旧版示例基于 `SkillSpec.dispatch_rules`（Skill 内部触发调度）+ `SkillAdapter`。
    - 方案2 已移除 Skill 原语：本仓库不再提供 `dispatch_rules` 语义，也不再维护“第二套调度系统”。

    推荐替代：
    - 用 WorkflowSpec 表达分支/并发/循环（可回归、可审计）
    - 用 TriggerFlow 做顶层编排（生态入口）
    - skills 的能力治理由 `agent_sdk` 提供（strict catalog + preflight + approvals + WAL）
    """

    print("=== 07_skill_dispatch（已迁移） ===")
    print("本仓已移除 `SkillSpec.dispatch_rules` / `SkillAdapter`（方案2）。")
    print("请用 `WorkflowSpec`（本仓）或 TriggerFlow（Agently）表达编排与分支。")
    print()
    print("参考：")
    print("- `docs/internal/specs/engineering-spec/02_Technical_Design/MULTI_AGENT_ORCHESTRATION.md`")
    print("- `docs/internal/specs/engineering-spec/02_Technical_Design/SKILLS_SYSTEM.md`")


if __name__ == "__main__":
    main()

