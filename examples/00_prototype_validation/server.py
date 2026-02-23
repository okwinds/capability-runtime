"""
Framework Validation Prototype（已迁移）。

本目录的旧实现用于验证 v0.4.0 的 `SkillSpec/SkillAdapter`（含 inject_to/dispatch_rules）。
方案2 已移除 Skill 原语，因此该原型已不再可运行。

替代入口：
- `archive/projects/agently-skills-web-prototype/`：参考应用（Host 侧）+ 场景回归

说明：
- 本仓库主线保持 bridge-only：skills 的发现/mention/sources/preflight/tools/approvals/WAL
  以 `skills-runtime-sdk-python`（模块 `agent_sdk`）为真相源。
"""

from __future__ import annotations


def main() -> None:
    print("examples/00_prototype_validation 已迁移。")
    print("请使用：`archive/projects/agently-skills-web-prototype/`。")


if __name__ == "__main__":
    main()

